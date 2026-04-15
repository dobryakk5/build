from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Integer, bindparam, func, select, text
from sqlalchemy.dialects import postgresql
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
from app.services.openrouter_embeddings import create_chat_completion, create_embeddings

LOW_CONFIDENCE_SCORE_THRESHOLD = 0.45

_GROUP_NORMALIZE_PROMPT = """Ты эксперт по строительным сметам России и ФЕР.
Нужно нормализовать название группы работ для поиска по разделам и сборникам ФЕР.

Правила:
- входной текст описывает группу работ, а не отдельную расценку
- раскрывай сокращения, но не выдумывай отсутствующие данные
- приводи формулировку к языку разделов и сборников ФЕР
- ответь одной строкой без пояснений
"""


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
class FerGroupCandidate:
    kind: str
    ref_id: int
    title: str
    collection_id: int
    collection_num: str | None
    collection_name: str | None
    score: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref_id": self.ref_id,
            "title": self.title,
            "collection_id": self.collection_id,
            "collection_num": self.collection_num,
            "collection_name": self.collection_name,
            "score": round(self.score, 4),
        }


@dataclass(slots=True)
class GroupMatchResult:
    kind: str | None
    ref_id: int | None
    title: str | None
    collection_id: int | None
    collection_num: str | None
    collection_name: str | None
    score: float | None
    is_ambiguous: bool
    candidates: list[FerGroupCandidate] | None
    no_match: bool

    def to_payload(self, estimate_id: str, matched_at: datetime | None = None) -> dict[str, Any]:
        return {
            "id": estimate_id,
            "fer_group_kind": self.kind,
            "fer_group_ref_id": self.ref_id,
            "fer_group_title": self.title,
            "fer_group_collection_id": self.collection_id,
            "fer_group_collection_num": self.collection_num,
            "fer_group_collection_name": self.collection_name,
            "fer_group_match_score": round(self.score, 4) if self.score is not None else None,
            "fer_group_matched_at": matched_at.isoformat() if matched_at else None,
            "fer_group_is_ambiguous": self.is_ambiguous,
            "fer_group_candidates": [candidate.to_payload() for candidate in self.candidates] if self.candidates else None,
            "no_match": self.no_match,
        }


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


def _build_estimate_group_search_text(estimate: Estimate) -> str:
    return str(estimate.section or "").strip()


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


def _group_gap(candidates: Sequence[FerGroupCandidate]) -> float | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return 1.0
    return float(candidates[0].score - candidates[1].score)


def _resolve_row_match_scope(
    estimate: Estimate,
    allowed_section_ids: Sequence[int] | None,
) -> tuple[list[int] | None, int | None, int | None]:
    group_ref_id = getattr(estimate, "fer_group_ref_id", None)
    group_kind = getattr(estimate, "fer_group_kind", None)
    group_collection_id = getattr(estimate, "fer_group_collection_id", None)
    group_is_ambiguous = bool(getattr(estimate, "fer_group_is_ambiguous", False))
    if group_ref_id and not group_is_ambiguous:
        if group_kind == "section":
            return None, int(group_ref_id), None
        if group_kind == "collection":
            collection_id = group_collection_id or group_ref_id
            return None, None, int(collection_id)
    return list(allowed_section_ids) if allowed_section_ids is not None else None, None, None


def _clear_group_binding(estimate: Estimate) -> None:
    estimate.fer_group_kind = None
    estimate.fer_group_ref_id = None
    estimate.fer_group_title = None
    estimate.fer_group_collection_id = None
    estimate.fer_group_collection_num = None
    estimate.fer_group_collection_name = None
    estimate.fer_group_match_score = None
    estimate.fer_group_matched_at = None
    estimate.fer_group_is_ambiguous = False
    estimate.fer_group_candidates = None


def _apply_group_match_result(estimate: Estimate, match: GroupMatchResult, matched_at: datetime | None) -> None:
    if match.no_match:
        _clear_group_binding(estimate)
        return

    estimate.fer_group_kind = match.kind
    estimate.fer_group_ref_id = match.ref_id
    estimate.fer_group_title = match.title
    estimate.fer_group_collection_id = match.collection_id
    estimate.fer_group_collection_num = match.collection_num
    estimate.fer_group_collection_name = match.collection_name
    estimate.fer_group_match_score = round(match.score, 4) if match.score is not None else None
    estimate.fer_group_matched_at = matched_at
    estimate.fer_group_is_ambiguous = match.is_ambiguous
    estimate.fer_group_candidates = [candidate.to_payload() for candidate in match.candidates] if match.candidates else None


def _candidate_from_payload(payload: dict[str, Any]) -> FerGroupCandidate:
    return FerGroupCandidate(
        kind=str(payload["kind"]),
        ref_id=int(payload["ref_id"]),
        title=str(payload["title"]),
        collection_id=int(payload["collection_id"]),
        collection_num=str(payload["collection_num"]) if payload.get("collection_num") is not None else None,
        collection_name=str(payload["collection_name"]) if payload.get("collection_name") is not None else None,
        score=float(payload["score"]),
    )


def confirm_group_candidate(estimate: Estimate, *, kind: str, ref_id: int) -> GroupMatchResult:
    candidates = estimate.fer_group_candidates or []
    for payload in candidates:
        if str(payload.get("kind")) == kind and int(payload.get("ref_id")) == int(ref_id):
            candidate = _candidate_from_payload(payload)
            return GroupMatchResult(
                kind=candidate.kind,
                ref_id=candidate.ref_id,
                title=candidate.title,
                collection_id=candidate.collection_id,
                collection_num=candidate.collection_num,
                collection_name=candidate.collection_name,
                score=candidate.score,
                is_ambiguous=False,
                candidates=None,
                no_match=False,
            )
    raise HTTPException(400, "Можно подтвердить только кандидата из текущего списка fer_group_candidates.")


async def get_manual_group_options(
    db: AsyncSession,
    estimate: Estimate,
) -> list[dict[str, Any]]:
    if not estimate.estimate_batch_id:
        raise HTTPException(400, "У строки сметы не указан блок сметы.")

    allowed_section_ids = await _get_allowed_section_ids_for_batch(db, estimate.estimate_batch_id)
    if not allowed_section_ids:
        raise HTTPException(
            400,
            "Для типа этой сметы не настроены разрешённые разделы ФЕР в fer.work_type_sections.",
        )

    stmt = text(
        """
        SELECT
            c.id AS collection_id,
            c.num AS collection_num,
            c.name AS collection_name,
            s.id AS section_id,
            s.title AS section_title
        FROM fer.sections s
        JOIN fer.collections c ON c.id = s.collection_id
        WHERE s.id = ANY(:allowed_section_ids)
          AND NOT (
              COALESCE(c.ignored, FALSE)
              OR COALESCE(s.ignored, FALSE)
          )
        ORDER BY c.num, s.id
        """
    ).bindparams(bindparam("allowed_section_ids", type_=postgresql.ARRAY(Integer)))

    rows = (
        await db.execute(stmt, {"allowed_section_ids": [int(section_id) for section_id in allowed_section_ids]})
    ).mappings().all()

    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        collection_id = int(row["collection_id"])
        bucket = grouped.setdefault(
            collection_id,
            {
                "id": collection_id,
                "num": str(row["collection_num"]).strip(),
                "name": str(row["collection_name"]).strip(),
                "sections": [],
            },
        )
        bucket["sections"].append(
            {
                "id": int(row["section_id"]),
                "title": str(row["section_title"]).strip(),
            }
        )

    return list(grouped.values())


async def resolve_manual_group_match(
    db: AsyncSession,
    estimate: Estimate,
    *,
    kind: str,
    ref_id: int,
) -> GroupMatchResult:
    if not estimate.estimate_batch_id:
        raise HTTPException(400, "У строки сметы не указан блок сметы.")

    allowed_section_ids = await _get_allowed_section_ids_for_batch(db, estimate.estimate_batch_id)
    if not allowed_section_ids:
        raise HTTPException(
            400,
            "Для типа этой сметы не настроены разрешённые разделы ФЕР в fer.work_type_sections.",
        )

    if kind == "section":
        stmt = text(
            """
            SELECT
                s.id AS ref_id,
                s.title AS title,
                c.id AS collection_id,
                c.num AS collection_num,
                c.name AS collection_name
            FROM fer.sections s
            JOIN fer.collections c ON c.id = s.collection_id
            WHERE s.id = :ref_id
              AND s.id = ANY(:allowed_section_ids)
              AND NOT (
                  COALESCE(c.ignored, FALSE)
                  OR COALESCE(s.ignored, FALSE)
              )
            """
        ).bindparams(bindparam("allowed_section_ids", type_=postgresql.ARRAY(Integer)))
        row = (
            await db.execute(
                stmt,
                {
                    "ref_id": int(ref_id),
                    "allowed_section_ids": [int(section_id) for section_id in allowed_section_ids],
                },
            )
        ).mappings().first()
        if row is None:
            raise HTTPException(400, "Выбранный раздел ФЕР недоступен для этого типа сметы.")
        return GroupMatchResult(
            kind="section",
            ref_id=int(row["ref_id"]),
            title=str(row["title"]).strip(),
            collection_id=int(row["collection_id"]),
            collection_num=str(row["collection_num"]).strip() if row["collection_num"] else None,
            collection_name=str(row["collection_name"]).strip() if row["collection_name"] else None,
            score=1.0,
            is_ambiguous=False,
            candidates=None,
            no_match=False,
        )

    if kind == "collection":
        allowed_collection_ids = await _get_allowed_collection_ids(db, allowed_section_ids)
        stmt = text(
            """
            SELECT
                c.id AS ref_id,
                concat('Сборник ', c.num, '. ', c.name) AS title,
                c.id AS collection_id,
                c.num AS collection_num,
                c.name AS collection_name
            FROM fer.collections c
            WHERE c.id = :ref_id
              AND c.id = ANY(:allowed_collection_ids)
              AND NOT COALESCE(c.ignored, FALSE)
            """
        ).bindparams(bindparam("allowed_collection_ids", type_=postgresql.ARRAY(Integer)))
        row = (
            await db.execute(
                stmt,
                {
                    "ref_id": int(ref_id),
                    "allowed_collection_ids": [int(collection_id) for collection_id in allowed_collection_ids],
                },
            )
        ).mappings().first()
        if row is None:
            raise HTTPException(400, "Выбранный сборник ФЕР недоступен для этого типа сметы.")
        return GroupMatchResult(
            kind="collection",
            ref_id=int(row["ref_id"]),
            title=str(row["title"]).strip(),
            collection_id=int(row["collection_id"]),
            collection_num=str(row["collection_num"]).strip() if row["collection_num"] else None,
            collection_name=str(row["collection_name"]).strip() if row["collection_name"] else None,
            score=1.0,
            is_ambiguous=False,
            candidates=None,
            no_match=False,
        )

    raise HTTPException(400, "kind должен быть 'collection' или 'section'.")


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


async def _normalize_group_title(raw_group_text: str) -> str:
    content = await create_chat_completion(
        model=settings.NORMALIZATION_MODEL,
        messages=[
            {"role": "system", "content": _GROUP_NORMALIZE_PROMPT},
            {"role": "user", "content": f"Название группы работ: {raw_group_text.strip()}"},
        ],
        temperature=0.0,
        max_tokens=180,
    )
    normalized = " ".join(content.split())
    return normalized or raw_group_text.strip()


async def _match_estimate_hybrid(
    db: AsyncSession,
    *,
    estimate: Estimate,
    normalized_text: str,
    embedding: Sequence[float],
    allowed_section_ids: Sequence[int] | None,
) -> MatchDecision:
    effective_allowed_section_ids, filter_section_id, filter_collection_id = _resolve_row_match_scope(
        estimate,
        allowed_section_ids,
    )
    candidates = await hybrid_search_candidates(
        db,
        normalized_text=normalized_text,
        embedding_literal=format_vector(embedding),
        allowed_section_ids=effective_allowed_section_ids,
        filter_section_id=filter_section_id,
        filter_collection_id=filter_collection_id,
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


async def match_estimate_group_with_vector(
    db: AsyncSession,
    estimate: Estimate,
) -> GroupMatchResult:
    if not await has_fer_vector_index_rows(db):
        raise HTTPException(400, "Векторный индекс ФЕР пуст. Сначала выполните векторизацию ФЕР.")

    raw_group_text = _build_estimate_group_search_text(estimate)
    if not raw_group_text:
        return GroupMatchResult(
            kind=None,
            ref_id=None,
            title=None,
            collection_id=None,
            collection_num=None,
            collection_name=None,
            score=None,
            is_ambiguous=False,
            candidates=None,
            no_match=True,
        )

    if not estimate.estimate_batch_id:
        raise HTTPException(400, "У строки сметы не указан блок сметы.")

    allowed_section_ids = await _get_allowed_section_ids_for_batch(db, estimate.estimate_batch_id)
    if not allowed_section_ids:
        raise HTTPException(
            400,
            "Для типа этой сметы не настроены разрешённые разделы ФЕР в fer.work_type_sections.",
        )

    try:
        normalized_text = await _normalize_group_title(raw_group_text)
    except Exception:
        normalized_text = raw_group_text

    embedding = (await create_embeddings([normalized_text]))[0]
    section_candidates = await _search_section_group_candidates(
        db,
        embedding=embedding,
        allowed_section_ids=allowed_section_ids,
        limit=2,
    )
    if section_candidates:
        section_gap = _group_gap(section_candidates)
        if (
            section_candidates[0].score >= float(settings.FER_GROUP_SECTION_SCORE_THRESHOLD)
            and (section_gap is None or section_gap >= float(settings.FER_GROUP_SECTION_GAP_THRESHOLD))
        ):
            top_candidate = section_candidates[0]
            return GroupMatchResult(
                kind="section",
                ref_id=top_candidate.ref_id,
                title=top_candidate.title,
                collection_id=top_candidate.collection_id,
                collection_num=top_candidate.collection_num,
                collection_name=top_candidate.collection_name,
                score=top_candidate.score,
                is_ambiguous=False,
                candidates=None,
                no_match=False,
            )

    allowed_collection_ids = await _get_allowed_collection_ids(db, allowed_section_ids)
    collection_candidates = await _search_collection_group_candidates(
        db,
        embedding=embedding,
        allowed_collection_ids=allowed_collection_ids,
        limit=3,
    )
    if not collection_candidates:
        return GroupMatchResult(
            kind=None,
            ref_id=None,
            title=None,
            collection_id=None,
            collection_num=None,
            collection_name=None,
            score=None,
            is_ambiguous=False,
            candidates=None,
            no_match=True,
        )

    top_candidate = collection_candidates[0]
    if top_candidate.score >= float(settings.FER_GROUP_COLLECTION_CONFIDENT_THRESHOLD):
        return GroupMatchResult(
            kind="collection",
            ref_id=top_candidate.ref_id,
            title=top_candidate.title,
            collection_id=top_candidate.collection_id,
            collection_num=top_candidate.collection_num,
            collection_name=top_candidate.collection_name,
            score=top_candidate.score,
            is_ambiguous=False,
            candidates=None,
            no_match=False,
        )

    if len(collection_candidates) == 1:
        return GroupMatchResult(
            kind="collection",
            ref_id=top_candidate.ref_id,
            title=top_candidate.title,
            collection_id=top_candidate.collection_id,
            collection_num=top_candidate.collection_num,
            collection_name=top_candidate.collection_name,
            score=top_candidate.score,
            is_ambiguous=False,
            candidates=None,
            no_match=False,
        )

    if (
        top_candidate.score >= float(settings.FER_GROUP_COLLECTION_AMBIGUOUS_THRESHOLD)
        or len(collection_candidates) > 1
    ):
        return GroupMatchResult(
            kind="collection",
            ref_id=top_candidate.ref_id,
            title=top_candidate.title,
            collection_id=top_candidate.collection_id,
            collection_num=top_candidate.collection_num,
            collection_name=top_candidate.collection_name,
            score=top_candidate.score,
            is_ambiguous=True,
            candidates=collection_candidates,
            no_match=False,
        )


async def _get_allowed_section_ids_for_batch(
    db: AsyncSession,
    estimate_batch_id: str | None,
) -> list[int]:
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


async def _get_allowed_collection_ids(
    db: AsyncSession,
    allowed_section_ids: Sequence[int],
) -> list[int]:
    if not allowed_section_ids:
        return []

    stmt = text(
        """
        SELECT DISTINCT s.collection_id
        FROM fer.sections s
        JOIN fer.collections c ON c.id = s.collection_id
        WHERE s.id = ANY(:allowed_section_ids)
          AND NOT (
              COALESCE(c.ignored, FALSE)
              OR COALESCE(s.ignored, FALSE)
          )
        ORDER BY s.collection_id
        """
    ).bindparams(bindparam("allowed_section_ids", type_=postgresql.ARRAY(Integer)))

    rows = (
        await db.execute(stmt, {"allowed_section_ids": [int(section_id) for section_id in allowed_section_ids]})
    ).scalars().all()
    return [int(value) for value in rows]


async def _search_section_group_candidates(
    db: AsyncSession,
    *,
    embedding: Sequence[float],
    allowed_section_ids: Sequence[int],
    limit: int,
) -> list[FerGroupCandidate]:
    if not allowed_section_ids:
        return []

    stmt = text(
        """
        SELECT
            s.id AS ref_id,
            s.title AS title,
            c.id AS collection_id,
            c.num AS collection_num,
            c.name AS collection_name,
            GREATEST(
                0.0,
                LEAST(
                    1.0,
                    1 - (vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector))
                )
            ) AS score
        FROM fer.vector_index vi
        JOIN fer.sections s ON s.id = vi.section_id
        JOIN fer.collections c ON c.id = s.collection_id
        WHERE vi.entity_kind = 'section'
          AND s.id = ANY(:allowed_section_ids)
          AND NOT (
              COALESCE(c.ignored, FALSE)
              OR COALESCE(s.ignored, FALSE)
          )
        ORDER BY vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector), vi.id
        LIMIT :limit
        """
    ).bindparams(bindparam("allowed_section_ids", type_=postgresql.ARRAY(Integer)))

    rows = (
        await db.execute(
            stmt,
            {
                "embedding": format_vector(embedding),
                "allowed_section_ids": [int(section_id) for section_id in allowed_section_ids],
                "limit": int(limit),
            },
        )
    ).mappings().all()
    return [
        FerGroupCandidate(
            kind="section",
            ref_id=int(row["ref_id"]),
            title=str(row["title"]).strip(),
            collection_id=int(row["collection_id"]),
            collection_num=str(row["collection_num"]).strip() if row["collection_num"] else None,
            collection_name=str(row["collection_name"]).strip() if row["collection_name"] else None,
            score=float(row["score"] or 0.0),
        )
        for row in rows
    ]


async def _search_collection_group_candidates(
    db: AsyncSession,
    *,
    embedding: Sequence[float],
    allowed_collection_ids: Sequence[int],
    limit: int,
) -> list[FerGroupCandidate]:
    if not allowed_collection_ids:
        return []

    stmt = text(
        """
        SELECT
            c.id AS ref_id,
            concat('Сборник ', c.num, '. ', c.name) AS title,
            c.id AS collection_id,
            c.num AS collection_num,
            c.name AS collection_name,
            GREATEST(
                0.0,
                LEAST(
                    1.0,
                    1 - (vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector))
                )
            ) AS score
        FROM fer.vector_index vi
        JOIN fer.collections c ON c.id = vi.collection_id
        WHERE vi.entity_kind = 'collection'
          AND c.id = ANY(:allowed_collection_ids)
          AND NOT COALESCE(c.ignored, FALSE)
        ORDER BY vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector), vi.id
        LIMIT :limit
        """
    ).bindparams(bindparam("allowed_collection_ids", type_=postgresql.ARRAY(Integer)))

    rows = (
        await db.execute(
            stmt,
            {
                "embedding": format_vector(embedding),
                "allowed_collection_ids": [int(collection_id) for collection_id in allowed_collection_ids],
                "limit": int(limit),
            },
        )
    ).mappings().all()
    return [
        FerGroupCandidate(
            kind="collection",
            ref_id=int(row["ref_id"]),
            title=str(row["title"]).strip(),
            collection_id=int(row["collection_id"]),
            collection_num=str(row["collection_num"]).strip() if row["collection_num"] else None,
            collection_name=str(row["collection_name"]).strip() if row["collection_name"] else None,
            score=float(row["score"] or 0.0),
        )
        for row in rows
    ]
