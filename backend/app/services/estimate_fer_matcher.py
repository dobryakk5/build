from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Estimate, EstimateBatch, Job
from app.services.fer_hybrid_search_service import (
    HybridCandidate,
    hybrid_search_candidates,
    llm_rerank,
    normalize_smeta_item,
    summarize_candidate_scores,
    should_rerank,
)
from app.services.fer_vector_index_service import format_vector
from app.services.openrouter_embeddings import create_embeddings

LOW_CONFIDENCE_SCORE_THRESHOLD = 0.45


@dataclass(slots=True)
class MatchResult:
    table_id: int | None
    work_type: str
    score: float
    normalized_text: str | None = None
    reranked: bool = False
    rerank_corrected: bool = False
    rerank_reason: str | None = None


@dataclass(slots=True)
class MatchDecision:
    match: MatchResult | None
    top1_score: float | None
    top2_score: float | None
    score_gap: float | None
    reranked: bool
    rerank_corrected: bool
    fallback_used: bool


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
        .where(EstimateBatch.deleted_at.is_(None))
    )
    if batch is None:
        raise HTTPException(404, "Блок сметы не найден")

    estimate_count = await db.scalar(
        select(func.count())
        .select_from(Estimate)
        .where(Estimate.project_id == project_id)
        .where(Estimate.estimate_batch_id == estimate_batch_id)
        .where(Estimate.deleted_at.is_(None))
    )
    if not estimate_count:
        raise HTTPException(400, "В выбранном блоке нет строк сметы")

    if not await has_fer_vector_index_rows(db):
        raise HTTPException(400, "Векторный индекс ФЕР пуст. Сначала выполните векторизацию ФЕР.")

    allowed_section_ids = await _get_allowed_section_ids_for_batch(db, estimate_batch_id)
    if not allowed_section_ids:
        raise HTTPException(
            400,
            "Для выбранного типа сметы не настроены разрешённые разделы ФЕР в fer.work_type_sections.",
        )

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
            allowed_section_ids = await _get_allowed_section_ids_for_batch(db, estimate_batch_id)
            if not allowed_section_ids:
                raise ValueError(
                    "Для выбранного типа сметы не настроены разрешённые разделы ФЕР в fer.work_type_sections."
                )
            estimates = list(
                await db.scalars(
                    select(Estimate)
                    .where(Estimate.project_id == job.project_id)
                    .where(Estimate.estimate_batch_id == estimate_batch_id)
                    .where(Estimate.deleted_at.is_(None))
                    .order_by(Estimate.row_order)
                )
            )
            if not estimates:
                raise ValueError("В блоке сметы не найдено строк для сопоставления")

            normalized_texts, normalization_fallbacks = await _normalize_estimates(estimates)
            embeddings = await create_embeddings(normalized_texts)

            matched_at = datetime.utcnow()
            matched_count = 0
            low_confidence_count = 0
            reranked_rows_count = 0
            rerank_corrected_count = 0
            fallback_rows_count = normalization_fallbacks

            for estimate in estimates:
                estimate.fer_table_id = None
                estimate.fer_work_type = None
                estimate.fer_match_score = None
                estimate.fer_matched_at = None

            for estimate, normalized_text, embedding in zip(estimates, normalized_texts, embeddings):
                decision = await _match_estimate_hybrid(
                    db,
                    estimate=estimate,
                    normalized_text=normalized_text,
                    embedding=embedding,
                    allowed_section_ids=allowed_section_ids,
                )
                if decision.match is None:
                    if decision.fallback_used:
                        fallback_rows_count += 1
                    continue

                estimate.fer_table_id = decision.match.table_id
                estimate.fer_work_type = decision.match.work_type
                estimate.fer_match_score = round(decision.match.score, 4)
                estimate.fer_matched_at = matched_at
                matched_count += 1

                if decision.match.score < LOW_CONFIDENCE_SCORE_THRESHOLD:
                    low_confidence_count += 1
                if decision.reranked:
                    reranked_rows_count += 1
                if decision.rerank_corrected:
                    rerank_corrected_count += 1
                if decision.fallback_used:
                    fallback_rows_count += 1

            job.status = "done"
            job.result = {
                "estimate_batch_id": estimate_batch_id,
                "estimate_batch_name": job.input.get("estimate_batch_name"),
                "matched_rows_count": matched_count,
                "low_confidence_count": low_confidence_count,
                "normalized_rows_count": len(normalized_texts),
                "reranked_rows_count": reranked_rows_count,
                "rerank_corrected_count": rerank_corrected_count,
                "fallback_rows_count": fallback_rows_count,
                "strategy": "fer_hybrid_llm",
            }
        except Exception as exc:
            job.status = "failed"
            job.result = {"error": str(exc), "strategy": "fer_hybrid_llm"}
        finally:
            job.finished_at = datetime.utcnow()
            await db.commit()


async def _normalize_estimates(estimates: Sequence[Estimate]) -> tuple[list[str], int]:
    semaphore = asyncio.Semaphore(4)
    normalized: list[str | None] = [None] * len(estimates)
    fallback_count = 0

    async def normalize_one(index: int, estimate: Estimate) -> None:
        nonlocal fallback_count
        fallback_text = _build_estimate_search_text(estimate)
        try:
            async with semaphore:
                normalized_text = await normalize_smeta_item(
                    section=estimate.section,
                    work_name=estimate.work_name,
                    unit=estimate.unit,
                )
            normalized[index] = normalized_text or fallback_text
        except Exception:
            normalized[index] = fallback_text
            fallback_count += 1

    await asyncio.gather(*(normalize_one(index, estimate) for index, estimate in enumerate(estimates)))
    return [item or _build_estimate_search_text(estimate) for item, estimate in zip(normalized, estimates)], fallback_count


async def _match_estimate_hybrid(
    db: AsyncSession,
    *,
    estimate: Estimate,
    normalized_text: str,
    embedding: Sequence[float],
    allowed_section_ids: Sequence[int] | None,
) -> MatchDecision:
    candidates = await hybrid_search_candidates(
        db,
        normalized_text=normalized_text,
        embedding_literal=format_vector(embedding),
        allowed_section_ids=allowed_section_ids,
        top_k=settings.RERANK_CANDIDATE_COUNT,
    )
    summary = summarize_candidate_scores(candidates)
    if not candidates or summary is None:
        return MatchDecision(
            match=None,
            top1_score=None,
            top2_score=None,
            score_gap=None,
            reranked=False,
            rerank_corrected=False,
            fallback_used=False,
        )

    top_candidate = candidates[0]
    selected_candidate = top_candidate
    reranked = False
    rerank_corrected = False
    fallback_used = False
    rerank_reason: str | None = None

    if should_rerank(candidates):
        reranked = True
        try:
            decision = await llm_rerank(
                original_text=estimate.work_name,
                normalized_text=normalized_text,
                candidates=candidates,
            )
            selected_candidate = decision.selected_candidate
            rerank_corrected = selected_candidate.table_id != top_candidate.table_id
            rerank_reason = decision.reason
        except Exception:
            fallback_used = True

    return MatchDecision(
        match=_candidate_to_match_result(
            selected_candidate,
            normalized_text=normalized_text,
            reranked=reranked and not fallback_used,
            rerank_corrected=rerank_corrected,
            rerank_reason=rerank_reason,
        ),
        top1_score=summary.top1_score,
        top2_score=summary.top2_score,
        score_gap=summary.score_gap,
        reranked=reranked and not fallback_used,
        rerank_corrected=rerank_corrected,
        fallback_used=fallback_used,
    )


def _candidate_to_match_result(
    candidate: HybridCandidate,
    *,
    normalized_text: str,
    reranked: bool,
    rerank_corrected: bool,
    rerank_reason: str | None,
) -> MatchResult:
    return MatchResult(
        table_id=candidate.table_id,
        work_type=candidate.work_type,
        score=float(candidate.final_score),
        normalized_text=normalized_text,
        reranked=reranked,
        rerank_corrected=rerank_corrected,
        rerank_reason=rerank_reason,
    )


async def has_fer_vector_index_rows(db: AsyncSession) -> bool:
    vector_index_count = await db.scalar(
        text("SELECT COUNT(*) FROM fer.vector_index WHERE entity_kind = 'row'")
    )
    return bool(vector_index_count)


async def match_estimate_with_vector(
    db: AsyncSession,
    estimate: Estimate,
) -> MatchResult | None:
    if not await has_fer_vector_index_rows(db):
        raise HTTPException(400, "Векторный индекс ФЕР пуст. Сначала выполните векторизацию ФЕР.")

    if not estimate.estimate_batch_id:
        raise HTTPException(400, "У строки сметы не указан блок сметы.")

    normalized_texts, _ = await _normalize_estimates([estimate])
    embedding = (await create_embeddings(normalized_texts))[0]
    allowed_section_ids = await _get_allowed_section_ids_for_batch(db, estimate.estimate_batch_id)
    if not allowed_section_ids:
        raise HTTPException(
            400,
            "Для типа этой сметы не настроены разрешённые разделы ФЕР в fer.work_type_sections.",
        )
    decision = await _match_estimate_hybrid(
        db,
        estimate=estimate,
        normalized_text=normalized_texts[0],
        embedding=embedding,
        allowed_section_ids=allowed_section_ids,
    )
    return decision.match


async def _get_allowed_section_ids_for_batch(
    db: AsyncSession,
    estimate_batch_id: str | None,
) -> list[int] | None:
    if not estimate_batch_id:
        return []

    row = (
        await db.execute(
            text(
                """
                SELECT wts.section_ids
                FROM estimate_batches eb
                LEFT JOIN fer.work_type_sections wts ON wts.id = eb.estimate_kind
                WHERE eb.id = :estimate_batch_id
                  AND eb.deleted_at IS NULL
                """
            ),
            {"estimate_batch_id": estimate_batch_id},
        )
    ).mappings().first()

    if row is None:
        return []

    section_ids = row.get("section_ids")
    if not section_ids:
        return []

    return [int(section_id) for section_id in section_ids]
