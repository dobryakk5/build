from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Estimate, EstimateBatch, Job
from app.services.openrouter_embeddings import create_embeddings


_LOW_CONFIDENCE_SCORE = 0.45


@dataclass(slots=True)
class MatchResult:
    table_id: int | None
    work_type: str
    score: float


def _build_estimate_search_text(estimate: Estimate) -> str:
    parts: list[str] = []
    if estimate.section and str(estimate.section).strip():
        parts.append(f"Раздел: {str(estimate.section).strip()}")
    parts.append(f"Работа: {str(estimate.work_name).strip()}")
    if estimate.unit and str(estimate.unit).strip():
        parts.append(f"Единица: {str(estimate.unit).strip()}")
    return "\n".join(parts)


async def start_fer_match_job(
    project_id: str,
    estimate_batch_id: str,
    user_id: str,
    db: AsyncSession,
) -> Job:
    batch = await db.scalar(
        select(EstimateBatch)
        .where(EstimateBatch.id == estimate_batch_id)
        .where(EstimateBatch.project_id == project_id)
        .where(EstimateBatch.deleted_at == None)
    )
    if batch is None:
        raise HTTPException(404, "Блок сметы не найден")

    estimate_count = await db.scalar(
        select(func.count())
        .select_from(Estimate)
        .where(Estimate.project_id == project_id)
        .where(Estimate.estimate_batch_id == estimate_batch_id)
        .where(Estimate.deleted_at == None)
    )
    if not estimate_count:
        raise HTTPException(400, "В выбранном блоке нет строк сметы")

    vector_index_count = await db.scalar(
        text("SELECT COUNT(*) FROM fer.vector_index WHERE entity_kind = 'row'")
    )
    if not vector_index_count:
        raise HTTPException(400, "Векторный индекс ФЕР пуст. Сначала выполните векторизацию ФЕР.")

    job = Job(
        id=str(uuid4()),
        type="estimate_fer_match",
        status="pending",
        project_id=project_id,
        created_by=user_id,
        input={
            "estimate_batch_id": estimate_batch_id,
            "estimate_batch_name": batch.name,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    asyncio.create_task(_process_fer_match(job.id))
    return job


async def _process_fer_match(job_id: str) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return

        estimate_batch_id = str(job.input.get("estimate_batch_id") or "")
        job.status = "processing"
        job.started_at = datetime.utcnow()
        await db.commit()

        try:
            estimates = list(
                await db.scalars(
                    select(Estimate)
                    .where(Estimate.project_id == job.project_id)
                    .where(Estimate.estimate_batch_id == estimate_batch_id)
                    .where(Estimate.deleted_at == None)
                    .order_by(Estimate.row_order)
                )
            )
            if not estimates:
                raise ValueError("В блоке сметы не найдено строк для сопоставления")

            search_texts = [_build_estimate_search_text(estimate) for estimate in estimates]
            embeddings = await create_embeddings(search_texts)

            matched_at = datetime.utcnow()
            matched_count = 0
            low_confidence_count = 0

            for estimate in estimates:
                estimate.fer_table_id = None
                estimate.fer_work_type = None
                estimate.fer_match_score = None
                estimate.fer_matched_at = None

            for estimate, embedding in zip(estimates, embeddings):
                match = await _find_best_vector_match(db, embedding)
                if match is None:
                    continue

                estimate.fer_table_id = match.table_id
                estimate.fer_work_type = match.work_type
                estimate.fer_match_score = round(match.score, 4)
                estimate.fer_matched_at = matched_at
                matched_count += 1
                if match.score < _LOW_CONFIDENCE_SCORE:
                    low_confidence_count += 1

            job.status = "done"
            job.result = {
                "estimate_batch_id": estimate_batch_id,
                "estimate_batch_name": job.input.get("estimate_batch_name"),
                "matched_rows_count": matched_count,
                "low_confidence_count": low_confidence_count,
                "strategy": "fer_vector_index",
            }
        except Exception as exc:
            job.status = "failed"
            job.result = {"error": str(exc), "strategy": "fer_vector_index"}
        finally:
            job.finished_at = datetime.utcnow()
            await db.commit()


async def _find_best_vector_match(
    db: AsyncSession,
    embedding: Sequence[float],
) -> MatchResult | None:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    vi.table_id,
                    COALESCE(NULLIF(t.common_work_name, ''), t.table_title, vi.source_text) AS work_type,
                    GREATEST(
                        0.0,
                        LEAST(
                            1.0,
                            1 - (vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector))
                        )
                    ) AS similarity
                FROM fer.vector_index vi
                LEFT JOIN fer.fer_tables t ON t.id = vi.table_id
                WHERE vi.entity_kind = 'row'
                ORDER BY vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector), vi.id
                LIMIT 1
                """
            ),
            {"embedding": _format_vector(embedding)},
        )
    ).mappings().first()

    if row is None or not row["work_type"]:
        return None

    return MatchResult(
        table_id=int(row["table_id"]) if row["table_id"] is not None else None,
        work_type=str(row["work_type"]).strip(),
        score=float(row["similarity"] or 0.0),
    )


def _format_vector(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.12f}" for value in values) + "]"
