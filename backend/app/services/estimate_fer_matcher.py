from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Estimate, EstimateBatch, Job


_TOKEN_RE = re.compile(r"[a-zа-я0-9]+", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_MULTISPACE_RE = re.compile(r"\s+")
_LOW_CONFIDENCE_SCORE = 0.45
_STEM_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "иях",
    "ах",
    "ях",
    "ия",
    "ья",
    "ие",
    "ье",
    "ий",
    "ый",
    "ой",
    "ая",
    "ое",
    "ее",
    "ые",
    "ых",
    "их",
    "ам",
    "ям",
    "ом",
    "ем",
    "ов",
    "ев",
    "ей",
    "ую",
    "юю",
    "а",
    "я",
    "ы",
    "и",
    "о",
    "е",
    "у",
    "ю",
    "ь",
)
_STOP_WORDS = {
    "без",
    "более",
    "в",
    "во",
    "внутри",
    "до",
    "для",
    "и",
    "из",
    "или",
    "к",
    "кг",
    "км",
    "м",
    "м2",
    "м3",
    "мм",
    "на",
    "над",
    "не",
    "один",
    "одного",
    "одной",
    "одно",
    "от",
    "по",
    "под",
    "при",
    "раз",
    "раза",
    "с",
    "слой",
    "слоя",
    "слоев",
    "со",
    "готов",
    "монтаж",
    "армирован",
    "установк",
    "устройство",
    "устройств",
}


@dataclass(slots=True)
class FerCandidate:
    table_id: int
    work_type: str
    normalized: str
    tokens: tuple[str, ...]


@dataclass(slots=True)
class MatchResult:
    table_id: int
    work_type: str
    score: float


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

            fallback_rows = await _fetch_fallback_candidate_rows(db)
            fallback_candidates = [_build_candidate(row) for row in fallback_rows if row["work_type"]]
            if not fallback_candidates:
                raise ValueError("В базе ФЕР нет записей для сопоставления")

            matched_at = datetime.utcnow()
            matched_count = 0
            low_confidence_count = 0
            candidate_cache: dict[str, list[FerCandidate]] = {}

            for estimate in estimates:
                query = _build_tsquery(estimate.work_name)
                if query not in candidate_cache:
                    if query:
                        rows = await _fetch_candidate_rows(db, query)
                        candidate_cache[query] = [_build_candidate(row) for row in rows if row["work_type"]]
                    else:
                        candidate_cache[query] = []

                candidates = candidate_cache[query] or fallback_candidates
                match = _match_best(str(estimate.work_name), candidates)
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
            }
        except Exception as exc:
            job.status = "failed"
            job.result = {"error": str(exc)}
        finally:
            job.finished_at = datetime.utcnow()
            await db.commit()


def _build_candidate(row: dict) -> FerCandidate:
    work_type = str(row["work_type"]).strip()
    search_text = " ".join(
        part.strip()
        for part in (
            work_type,
            row.get("table_title") or "",
        )
        if part and str(part).strip()
    )
    normalized = _normalize_text(search_text)
    return FerCandidate(
        table_id=int(row["id"]),
        work_type=work_type,
        normalized=_normalize_text(work_type),
        tokens=tuple(_tokenize(normalized)),
    )


def _match_best(estimate_name: str, candidates: Iterable[FerCandidate]) -> MatchResult | None:
    normalized = _normalize_text(estimate_name)
    estimate_tokens = tuple(_tokenize(normalized))
    candidate_list = list(candidates)

    matched_token_counts = {
        candidate.table_id: _shared_token_count(estimate_tokens, candidate.tokens)
        for candidate in candidate_list
    }
    candidate_pool = [
        candidate
        for candidate in candidate_list
        if matched_token_counts[candidate.table_id] > 0
    ] or candidate_list

    best_candidate: FerCandidate | None = None
    best_score = -1.0

    for candidate in candidate_pool:
        score = _score_match(
            normalized,
            estimate_tokens,
            candidate,
            matched_token_counts.get(candidate.table_id, 0),
        )
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None:
        return None

    return MatchResult(
        table_id=best_candidate.table_id,
        work_type=best_candidate.work_type,
        score=max(0.0, min(best_score, 1.0)),
    )


async def _fetch_candidate_rows(db: AsyncSession, query: str) -> list[dict]:
    return (
        await db.execute(
            text(
                """
                SELECT
                    t.id,
                    COALESCE(NULLIF(t.common_work_name, ''), t.table_title) AS work_type,
                    t.table_title
                FROM fer.fer_tables t
                WHERE to_tsvector('russian', COALESCE(NULLIF(t.common_work_name, ''), '') || ' ' || t.table_title)
                      @@ to_tsquery('russian', :query)
                ORDER BY ts_rank_cd(
                    to_tsvector('russian', COALESCE(NULLIF(t.common_work_name, ''), '') || ' ' || t.table_title),
                    to_tsquery('russian', :query)
                ) DESC, t.id
                LIMIT 40
                """
            ),
            {"query": query},
        )
    ).mappings().all()


async def _fetch_fallback_candidate_rows(db: AsyncSession) -> list[dict]:
    return (
        await db.execute(
            text(
                """
                SELECT
                    t.id,
                    COALESCE(NULLIF(t.common_work_name, ''), t.table_title) AS work_type,
                    t.table_title
                FROM fer.fer_tables t
                ORDER BY t.id
                """
            )
        )
    ).mappings().all()


def _build_tsquery(work_name: str) -> str:
    tokens = list(dict.fromkeys(_tokenize(_normalize_text(work_name))))
    return " | ".join(f"{token}:*" for token in tokens)


def _score_match(
    estimate_text: str,
    estimate_tokens: tuple[str, ...],
    candidate: FerCandidate,
    matched_token_count: int,
) -> float:
    if not estimate_text or not candidate.normalized:
        return 0.0

    token_overlap = _token_recall(estimate_tokens, candidate.tokens)
    sequence_score = SequenceMatcher(None, estimate_text, candidate.normalized).ratio()
    leading_token_bonus = 0.0
    if estimate_tokens and _token_matches_any(estimate_tokens[0], candidate.tokens):
        leading_token_bonus = 0.12

    return (
        (token_overlap * 0.75)
        + (sequence_score * 0.25)
        + (min(matched_token_count, 3) * 0.03)
        + leading_token_bonus
    )


def _normalize_text(value: str) -> str:
    lowered = value.lower().replace("ё", "е")
    without_numbers = _NUMBER_RE.sub(" ", lowered)
    cleaned = " ".join(_TOKEN_RE.findall(without_numbers))
    return _MULTISPACE_RE.sub(" ", cleaned).strip()


def _tokenize(value: str) -> list[str]:
    return [
        _stem_token(token)
        for token in value.split()
        if len(token) > 2 and _stem_token(token) not in _STOP_WORDS
    ]


def _stem_token(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix in _STEM_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def _token_recall(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if not left or not right:
        return 0.0

    used: set[int] = set()
    score = 0.0

    for left_token in left:
        best_score = 0.0
        best_index: int | None = None
        for index, right_token in enumerate(right):
            if index in used:
                continue
            similarity = _token_similarity(left_token, right_token)
            if similarity > best_score:
                best_score = similarity
                best_index = index
        if best_index is not None:
            used.add(best_index)
            score += best_score

    return score / len(left)


def _shared_token_count(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    count = 0
    used: set[int] = set()

    for left_token in left:
        for index, right_token in enumerate(right):
            if index in used:
                continue
            if _token_similarity(left_token, right_token) > 0:
                used.add(index)
                count += 1
                break
    return count


def _token_matches_any(token: str, candidates: tuple[str, ...]) -> bool:
    return any(_token_similarity(token, candidate) > 0 for candidate in candidates)


def _token_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if left.startswith(right) or right.startswith(left):
        return 0.92

    common_prefix = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        common_prefix += 1

    if common_prefix >= 5:
        return 0.75
    return 0.0
