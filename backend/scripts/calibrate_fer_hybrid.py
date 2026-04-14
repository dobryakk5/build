from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from sqlalchemy import select


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import Estimate, EstimateBatch
from app.services.estimate_fer_matcher import _build_estimate_search_text, _get_allowed_section_ids_for_batch
from app.services.fer_hybrid_search_service import (
    hybrid_search_candidates,
    normalize_smeta_item,
    summarize_candidate_scores,
)
from app.services.fer_vector_index_service import format_vector
from app.services.openrouter_embeddings import create_embeddings


@dataclass(slots=True)
class CalibrationRow:
    estimate_id: str
    row_order: int | None
    work_name: str
    normalized_text: str
    top1_table_id: int | None
    top1_work_type: str | None
    top1_score: float | None
    top2_score: float | None
    score_gap: float | None
    candidates_count: int
    top_candidates: list[dict[str, object]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run hybrid FER calibration on an estimate batch without rerank.",
    )
    parser.add_argument("--batch-id", default=None, help="Estimate batch id. Defaults to the latest batch.")
    parser.add_argument("--project-id", default=None, help="Optional project id filter when resolving latest batch.")
    parser.add_argument("--output", default=None, help="Optional path to save detailed JSON.")
    parser.add_argument("--sample-size", type=int, default=10, help="How many ambiguous rows to print.")
    return parser.parse_args()


def percentile(values: Sequence[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * ratio))
    return float(ordered[index])


async def resolve_batch(args: argparse.Namespace) -> EstimateBatch:
    async with AsyncSessionLocal() as db:
        if args.batch_id:
            batch = await db.get(EstimateBatch, args.batch_id)
            if batch is None:
                raise RuntimeError(f"Estimate batch not found: {args.batch_id}")
            return batch

        stmt = select(EstimateBatch).where(EstimateBatch.deleted_at.is_(None))
        if args.project_id:
            stmt = stmt.where(EstimateBatch.project_id == args.project_id)
        stmt = stmt.order_by(EstimateBatch.created_at.desc())

        batch = await db.scalar(stmt.limit(1))
        if batch is None:
            raise RuntimeError("No estimate batches found for calibration.")
        return batch


async def fetch_estimates(batch_id: str, project_id: str) -> list[Estimate]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Estimate)
                .where(Estimate.estimate_batch_id == batch_id)
                .where(Estimate.project_id == project_id)
                .where(Estimate.deleted_at.is_(None))
                .order_by(Estimate.row_order, Estimate.id)
            )
        )


async def normalize_estimates(estimates: Sequence[Estimate]) -> list[str]:
    semaphore = asyncio.Semaphore(4)
    normalized: list[str | None] = [None] * len(estimates)

    async def normalize_one(index: int, estimate: Estimate) -> None:
        fallback = _build_estimate_search_text(estimate)
        try:
            async with semaphore:
                value = await normalize_smeta_item(
                    section=estimate.section,
                    work_name=estimate.work_name,
                    unit=estimate.unit,
                )
            normalized[index] = value or fallback
        except Exception:
            normalized[index] = fallback

    await asyncio.gather(*(normalize_one(index, estimate) for index, estimate in enumerate(estimates)))
    return [item or _build_estimate_search_text(estimate) for item, estimate in zip(normalized, estimates)]


async def calibrate_batch(batch: EstimateBatch) -> tuple[list[CalibrationRow], list[int]]:
    estimates = await fetch_estimates(str(batch.id), str(batch.project_id))
    if not estimates:
        raise RuntimeError("Estimate batch contains no rows.")

    normalized_texts = await normalize_estimates(estimates)
    embeddings = await create_embeddings(normalized_texts)

    async with AsyncSessionLocal() as db:
        allowed_section_ids = await _get_allowed_section_ids_for_batch(db, str(batch.id))
        rows: list[CalibrationRow] = []
        for estimate, normalized_text, embedding in zip(estimates, normalized_texts, embeddings):
            candidates = await hybrid_search_candidates(
                db,
                normalized_text=normalized_text,
                embedding_literal=format_vector(embedding),
                allowed_section_ids=allowed_section_ids,
                top_k=settings.RERANK_CANDIDATE_COUNT,
            )
            summary = summarize_candidate_scores(candidates)
            top_candidate = candidates[0] if candidates else None
            rows.append(
                CalibrationRow(
                    estimate_id=str(estimate.id),
                    row_order=estimate.row_order,
                    work_name=estimate.work_name,
                    normalized_text=normalized_text,
                    top1_table_id=top_candidate.table_id if top_candidate else None,
                    top1_work_type=top_candidate.work_type if top_candidate else None,
                    top1_score=summary.top1_score if summary else None,
                    top2_score=summary.top2_score if summary else None,
                    score_gap=summary.score_gap if summary else None,
                    candidates_count=len(candidates),
                    top_candidates=[
                        {
                            "rank": index,
                            "table_id": candidate.table_id,
                            "work_type": candidate.work_type,
                            "source_text": candidate.source_text,
                            "final_score": candidate.final_score,
                            "vec_score": candidate.vec_score,
                            "fts_score": candidate.fts_score,
                        }
                        for index, candidate in enumerate(candidates[:5], start=1)
                    ],
                )
            )

    return rows, allowed_section_ids


def print_summary(rows: Sequence[CalibrationRow], sample_size: int) -> None:
    def fmt(value: float | None) -> str:
        return f"{value:.4f}" if value is not None else "n/a"

    scores = [row.top1_score for row in rows if row.top1_score is not None]
    gaps = [row.score_gap for row in rows if row.score_gap is not None]

    print("Calibration rows:", len(rows))
    print("Top-1 score stats:")
    print(
        "  min={:.4f} p25={} median={} p75={} p90={} max={:.4f}".format(
            min(scores) if scores else 0.0,
            f"{percentile(scores, 0.25):.4f}" if percentile(scores, 0.25) is not None else "n/a",
            f"{statistics.median(scores):.4f}" if scores else "n/a",
            f"{percentile(scores, 0.75):.4f}" if percentile(scores, 0.75) is not None else "n/a",
            f"{percentile(scores, 0.90):.4f}" if percentile(scores, 0.90) is not None else "n/a",
            max(scores) if scores else 0.0,
        )
    )
    print("Gap stats:")
    print(
        "  min={:.4f} p25={} median={} p75={} p90={} max={:.4f}".format(
            min(gaps) if gaps else 0.0,
            f"{percentile(gaps, 0.25):.4f}" if percentile(gaps, 0.25) is not None else "n/a",
            f"{statistics.median(gaps):.4f}" if gaps else "n/a",
            f"{percentile(gaps, 0.75):.4f}" if percentile(gaps, 0.75) is not None else "n/a",
            f"{percentile(gaps, 0.90):.4f}" if percentile(gaps, 0.90) is not None else "n/a",
            max(gaps) if gaps else 0.0,
        )
    )

    ambiguous = sorted(
        [row for row in rows if row.top1_score is not None],
        key=lambda row: (
            row.top1_score if row.top1_score is not None else 1.0,
            row.score_gap if row.score_gap is not None else 1.0,
        ),
    )[:sample_size]
    print(f"Ambiguous sample ({len(ambiguous)} rows):")
    for row in ambiguous:
        print(f"- row_order={row.row_order} estimate_id={row.estimate_id}")
        print(f"  work_name={row.work_name}")
        print(f"  normalized={row.normalized_text}")
        print(
            f"  top1_score={fmt(row.top1_score)} "
            f"top2_score={fmt(row.top2_score)} "
            f"gap={fmt(row.score_gap)}"
        )
        for candidate in row.top_candidates[:3]:
            print(
                "  candidate {rank}: table_id={table_id} final={final_score:.4f} vec={vec_score:.4f} fts={fts_score:.4f} :: {work_type}".format(
                    **candidate
                )
            )


async def main() -> None:
    args = parse_args()
    batch = await resolve_batch(args)
    rows, allowed_section_ids = await calibrate_batch(batch)

    print("Batch id:", batch.id)
    print("Project id:", batch.project_id)
    print("Batch name:", batch.name)
    print("Allowed FER sections:", allowed_section_ids or "all")
    print_summary(rows, args.sample_size)

    if args.output:
        payload = {
            "batch_id": str(batch.id),
            "project_id": str(batch.project_id),
            "batch_name": batch.name,
            "allowed_section_ids": allowed_section_ids,
            "rows": [asdict(row) for row in rows],
        }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Saved detailed report:", output_path)


if __name__ == "__main__":
    asyncio.run(main())
