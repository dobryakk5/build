"""
Item-level NW → ФЕР matching for WBS items (post Stage 1).

Goal: ground task durations in real ФЕР labor norms (fer.fer_rows.h_hour) instead
of LLM guesses. For each `from_estimate` WBS item we:

  A. classify non-work rows (ИТОГО/субитоги/сервис) → disposition='excluded';
  B. derive an NW scope (estimate_nw_matcher) — used ONLY to narrow the ФЕР search;
  C. match the item to a concrete ФЕР row via hybrid search + rerank, storing
     fer_table_id/fer_row_id/fer_h_hour and a reconciled unit/multiplier.

NW classification quality is secondary here — the duration signal lives in h_hour.
Acceptance is conservative (see `_decide_fer_match`); anything not auto-accepted is
stored as candidates and left for operator review.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Estimate
from app.models.ktp_estimate import KtpEstimateSession, KtpWbsGroup, KtpWbsItem
from app.services.estimate_nw_matcher import match_estimate_row
from app.services.fer_hybrid_search_service import (
    HybridCandidate,
    hybrid_search_candidates,
    llm_rerank,
    normalize_smeta_item,
    should_rerank,
    summarize_candidate_scores,
)
from app.services.fer_vector_index_service import format_vector
from app.services.nw_palette_service import get_palette
from app.services.openrouter_embeddings import create_embeddings

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], Awaitable[None]] | None


async def _write_fer_detail_log(
    _db: AsyncSession,
    session: KtpEstimateSession,
    *,
    message: str,
    group: KtpWbsGroup | None = None,
    step: str,
    meta: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "KTP FER match | session=%s project=%s group=%s step=%s message=%s meta=%s",
        session.id,
        session.project_id,
        group.id if group else None,
        step,
        message,
        {
            "group_title": group.title if group else None,
            **(meta or {}),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step A — non-work detection
# ─────────────────────────────────────────────────────────────────────────────
# Conservative: only patterns that are almost never a real construction work line.
_NONWORK_PATTERNS = [
    r"^\s*итого\b",
    r"^\s*всего\b",
    r"\bитого\s+(?:за|по)\b",
    r"^\s*[Σ∑]",  # Σ
    r"накладн\w*\s+расход",
    r"сметн\w*\s+прибыл",
    r"^\s*коэффициент\b",
    r"непредвиденн\w*\s+(?:расход|затрат)",
    r"выезд\s+мастер",
    r"транспортн\w*\s+расход",
]
_NONWORK_COMPILED = [re.compile(p, re.IGNORECASE) for p in _NONWORK_PATTERNS]


def classify_disposition(name: str) -> tuple[str, str | None, str | None]:
    """Returns (disposition, reason, source). 'work' or 'excluded'."""
    text_l = (name or "").strip()
    if not text_l:
        return "excluded", "пустая строка", "regex"
    for rx in _NONWORK_COMPILED:
        if rx.search(text_l):
            return "excluded", f"не работа (паттерн: {rx.pattern})", "regex"
    return "work", None, None


# ─────────────────────────────────────────────────────────────────────────────
# Unit reconciliation (honest v1: fer.fer_rows has no unit column)
# ─────────────────────────────────────────────────────────────────────────────
# We extract a coarse unit + multiplier from the ФЕР table header/row text.
# FER norms are commonly stated "на 100 м2" / "на 1000 м3"; h_hour is per that
# multiple, so labor = (quantity / multiplier) * h_hour.

_UNIT_NORMALIZERS: list[tuple[str, str]] = [
    (r"м\s*3|куб\.?\s*м|м³", "м3"),
    (r"м\s*2|кв\.?\s*м|м²", "м2"),
    (r"м\.?\s*пог|пог\.?\s*м|п\.?\s*м|м\.п", "м"),
    (r"\bтонн\w*|\bт\b", "т"),
    (r"\bкг\b", "кг"),
    (r"\bшт\w*", "шт"),
    (r"\bкомпл\w*", "компл"),
    (r"\bм\b", "м"),
]
_UNIT_COMPILED = [(re.compile(p, re.IGNORECASE), u) for p, u in _UNIT_NORMALIZERS]


def normalize_unit(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lower().replace(" ", "")
    if not s:
        return None
    for rx, norm in _UNIT_COMPILED:
        if rx.search(s):
            return norm
    return None


def extract_fer_unit(*texts: str | None) -> tuple[str | None, float]:
    """Best-effort (unit, multiplier) from a ФЕР table title / row text."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None, 1.0
    multiplier = 1.0
    m = re.search(r"\bна\s+(\d{1,4})\b", blob)
    if m:
        try:
            multiplier = float(m.group(1))
        except ValueError:
            multiplier = 1.0
    return normalize_unit(blob), multiplier


# ─────────────────────────────────────────────────────────────────────────────
# Step C — acceptance policy (reuses should_rerank/llm_rerank gate)
# ─────────────────────────────────────────────────────────────────────────────
async def _decide_fer_match(
    candidates: Sequence[HybridCandidate],
    *,
    original_text: str,
    normalized_text: str,
) -> tuple[HybridCandidate | None, str, float | None]:
    """Returns (candidate, source, score). source ∈ {'auto','review'}.

    Conservative and robust to RERANK_ENABLED being off: a candidate is only
    auto-accepted when the hybrid score clears RERANK_SCORE_THRESHOLD/GAP, or
    (when rerank is on) the rerank is confident and didn't override the top pick.
    """
    summary = summarize_candidate_scores(candidates)
    if not candidates or summary is None:
        return None, "review", None

    top = candidates[0]
    strong = summary.top1_score >= float(settings.RERANK_SCORE_THRESHOLD) and (
        summary.score_gap is None
        or summary.score_gap >= float(settings.RERANK_GAP_THRESHOLD)
    )
    if strong:
        return top, "auto", summary.top1_score

    if settings.RERANK_ENABLED and should_rerank(candidates):
        try:
            decision = await llm_rerank(
                original_text=original_text,
                normalized_text=normalized_text,
                candidates=candidates,
            )
        except Exception:  # noqa: BLE001
            logger.exception("llm_rerank failed during item ФЕР match")
            return top, "review", summary.top1_score
        if not decision.corrected and decision.confidence >= float(
            settings.RERANK_SCORE_THRESHOLD
        ):
            return decision.selected_candidate, "auto", decision.confidence
        return decision.selected_candidate, "review", decision.confidence

    return top, "review", summary.top1_score


def _candidates_payload(candidates: Sequence[HybridCandidate], limit: int = 5) -> list[dict]:
    return [
        {
            "table_id": c.table_id,
            "row_id": c.row_id,
            "work_type": c.work_type,
            "final_score": round(float(c.final_score), 4),
        }
        for c in candidates[:limit]
    ]


# ─────────────────────────────────────────────────────────────────────────────
# NW scope helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _allowed_table_ids_for_nw(
    db: AsyncSession, nw_codes: Sequence[str]
) -> list[int]:
    """ФЕР tables directly mapped to the given NW codes (search scope)."""
    codes = [c for c in nw_codes if c]
    if not codes:
        return []
    rows = await db.execute(
        text(
            """
            SELECT DISTINCT fer_table_id
            FROM fer.nw_fer_table_mapping
            WHERE mapping_type = 'direct'
              AND nw_item_code = ANY(:codes)
            """
        ),
        {"codes": codes},
    )
    return [int(r[0]) for r in rows.all() if r[0] is not None]


async def _fer_rows_meta(
    db: AsyncSession, row_ids: Sequence[int]
) -> dict[int, dict[str, Any]]:
    """row_id -> {h_hour, table_title, row_slug, clarification}."""
    ids = [r for r in row_ids if r]
    if not ids:
        return {}
    rows = await db.execute(
        text(
            """
            SELECT r.id, r.h_hour, r.row_slug, r.clarification, t.table_title
            FROM fer.fer_rows r
            LEFT JOIN fer.fer_tables t ON t.id = r.table_id
            WHERE r.id = ANY(:ids)
            """
        ),
        {"ids": ids},
    )
    out: dict[int, dict[str, Any]] = {}
    for row in rows.mappings():
        out[int(row["id"])] = dict(row)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────
async def match_session_items(
    db: AsyncSession,
    session: KtpEstimateSession,
    estimate_kind: int,
    groups: list[KtpWbsGroup],
    items: list[KtpWbsItem],
    on_progress: ProgressCb = None,
) -> dict[str, int]:
    """Run Steps A–C over the session's `from_estimate` items (mutates items)."""
    # Estimate source rows (section / original work_name for richer matching text).
    estimate_ids = [it.estimate_id for it in items if it.estimate_id]
    estimates: dict[str, Estimate] = {}
    if estimate_ids:
        estimates = {
            e.id: e
            for e in await db.scalars(
                select(Estimate).where(Estimate.id.in_(estimate_ids))
            )
        }

    # Palette → NW codes and per-WT scopes.
    palette = await get_palette(db, estimate_kind)
    all_nw_codes = [p["nw_item_code"] for p in palette]
    wt_to_nw: dict[str, list[str]] = {}
    for p in palette:
        wt_to_nw.setdefault(p["work_type_code"], []).append(p["nw_item_code"])

    # Candidate work items (skip ai_added/manual and manual overrides), processed
    # group-by-group so progress and journal logs point at a concrete WBS block.
    work_items_by_group: dict[str, list[KtpWbsItem]] = {g.id: [] for g in groups}
    for it in items:
        if (
            it.origin == "from_estimate"
            and it.review_status != "rejected"
            and not it.fer_manual_override
        ):
            work_items_by_group.setdefault(it.group_id, []).append(it)

    group_batches = [
        (g, sorted(work_items_by_group.get(g.id, []), key=lambda x: float(x.sort_order)))
        for g in sorted(groups, key=lambda x: float(x.sort_order))
        if work_items_by_group.get(g.id)
    ]

    stats = {"excluded": 0, "matched_auto": 0, "matched_review": 0, "no_match": 0}
    total_candidates = sum(len(batch_items) for _g, batch_items in group_batches)
    if not total_candidates:
        return stats

    if on_progress:
        await on_progress(
            f"Сопоставление с ФЕР по группам: {len(group_batches)} групп, "
            f"{total_candidates} позиций…"
        )
    await _write_fer_detail_log(
        db,
        session,
        message=(
            f"Запущено сопоставление ФЕР по группам: {len(group_batches)} групп, "
            f"{total_candidates} позиций."
        ),
        step="start",
        meta={"groups_count": len(group_batches), "items_count": total_candidates},
    )

    # ── Shared caches for all groups ─────────────────────────────────────────
    nw_table_cache: dict[tuple[str, ...], list[int]] = {}

    async def _scope_cached(codes: Sequence[str]) -> list[int]:
        key = tuple(sorted(set(codes)))
        if key not in nw_table_cache:
            nw_table_cache[key] = await _allowed_table_ids_for_nw(db, codes)
        return nw_table_cache[key]

    sem = asyncio.Semaphore(max(1, int(settings.FER_MATCH_CONCURRENCY)))
    batch_size = max(1, int(settings.FER_MATCH_BATCH_SIZE))

    for group_idx, (group, group_items) in enumerate(group_batches, start=1):
        group_prefix = f"Группа {group_idx}/{len(group_batches)}: {group.title}"
        await _write_fer_detail_log(
            db,
            session,
            group=group,
            step="group_start",
            message=f"{group_prefix}. Старт ФЕР-сопоставления: {len(group_items)} позиций.",
            meta={
                "group_index": group_idx,
                "groups_count": len(group_batches),
                "items_count": len(group_items),
                "sample_items": [it.name for it in group_items[:20]],
            },
        )
        if on_progress:
            await on_progress(f"{group_prefix}: фильтрация {len(group_items)} позиций…")

        to_match: list[KtpWbsItem] = []
        group_excluded = 0
        for it in group_items:
            disp, reason, src = classify_disposition(it.name)
            if disp == "excluded":
                it.disposition = "excluded"
                it.disposition_reason = reason
                it.disposition_source = src
                stats["excluded"] += 1
                group_excluded += 1
                continue
            it.disposition = "work"
            to_match.append(it)

        await _write_fer_detail_log(
            db,
            session,
            group=group,
            step="excluded",
            message=(
                f"{group_prefix}. После фильтрации: {len(to_match)} рабочих позиций, "
                f"{group_excluded} исключено."
            ),
            meta={"to_match": len(to_match), "excluded": group_excluded},
        )
        if not to_match:
            continue

        # ── Step B — NW scope + search-text per item ────────────────────────
        table_scope_for_item: dict[str, list[int]] = {}
        search_text_for_item: dict[str, str] = {}

        if on_progress:
            await on_progress(f"{group_prefix}: NW-скоуп 0/{len(to_match)}…")
        for idx, it in enumerate(to_match, start=1):
            est = estimates.get(it.estimate_id) if it.estimate_id else None
            section = est.section if est else None
            work_text = (est.work_name if est and est.work_name else it.name) or it.name
            search_text_for_item[it.id] = work_text

            narrow = wt_to_nw.get(group.wt_code or "", [])
            m = match_estimate_row(
                work_text,
                section,
                allowed_nw_codes=narrow or all_nw_codes or None,
            )
            it.nw_item_code = m.nw_code
            it.nw_match_reason = m.note
            if m.nw_code and m.confidence in set(settings.NW_KEYWORD_AUTO_LEVELS):
                it.nw_match_source = "keyword" if narrow else "broad"
            else:
                it.nw_match_source = None
            it.nw_match_candidates = (
                [{"nw_code": m.nw_code, "confidence": m.confidence, "source": m.source}]
                if m.nw_code
                else None
            )

            # ФЕР table scope: matched NW → its tables; else narrow WT NW set; else global.
            if m.nw_code:
                scope = await _scope_cached([m.nw_code])
            elif narrow:
                scope = await _scope_cached(narrow)
            else:
                scope = []
            table_scope_for_item[it.id] = scope
            if on_progress and (idx % 25 == 0 or idx == len(to_match)):
                await on_progress(f"{group_prefix}: NW-скоуп {idx}/{len(to_match)}…")

        await _write_fer_detail_log(
            db,
            session,
            group=group,
            step="nw_scope",
            message=f"{group_prefix}. NW-скоуп рассчитан для {len(to_match)} позиций.",
            meta={
                "nw_matched": sum(1 for it in to_match if it.nw_item_code),
                "with_table_scope": sum(1 for it in to_match if table_scope_for_item.get(it.id)),
            },
        )

        # ── Step C.1 — normalize search text ────────────────────────────────
        normalized: dict[str, str] = {}

        async def _normalize_one(it: KtpWbsItem) -> tuple[str, str]:
            raw = search_text_for_item[it.id]
            try:
                async with sem:
                    norm = await normalize_smeta_item(
                        section=None, work_name=raw, unit=it.unit
                    )
                return it.id, norm or raw
            except Exception:  # noqa: BLE001
                logger.exception("Normalization failed during item ФЕР match")
                return it.id, raw

        if on_progress:
            await on_progress(f"{group_prefix}: нормализация 0/{len(to_match)}…")
        await _write_fer_detail_log(
            db,
            session,
            group=group,
            step="normalization_start",
            message=f"{group_prefix}. Запущена нормализация {len(to_match)} позиций.",
            meta={"items_count": len(to_match)},
        )
        normalize_tasks = [asyncio.create_task(_normalize_one(it)) for it in to_match]
        for completed, task in enumerate(asyncio.as_completed(normalize_tasks), start=1):
            item_id, normalized_text = await task
            normalized[item_id] = normalized_text
            if completed % 25 == 0 or completed == len(to_match):
                msg = f"{group_prefix}: нормализация {completed}/{len(to_match)}…"
                if on_progress:
                    await on_progress(msg)
                await _write_fer_detail_log(
                    db,
                    session,
                    group=group,
                    step="normalization_progress",
                    message=msg,
                    meta={"completed": completed, "total": len(to_match)},
                )

        # ── Step C.2 — embeddings ───────────────────────────────────────────
        embeddings: dict[str, list[float]] = {}
        for start in range(0, len(to_match), batch_size):
            chunk = to_match[start : start + batch_size]
            try:
                vecs = await create_embeddings([normalized[it.id] for it in chunk])
                for it, vec in zip(chunk, vecs):
                    embeddings[it.id] = vec
            except Exception:  # noqa: BLE001
                logger.exception("Embedding batch failed during item ФЕР match")
            completed = min(start + batch_size, len(to_match))
            msg = f"{group_prefix}: векторизация {completed}/{len(to_match)}…"
            if on_progress:
                await on_progress(msg)
            await _write_fer_detail_log(
                db,
                session,
                group=group,
                step="embeddings_progress",
                message=msg,
                meta={"completed": completed, "total": len(to_match)},
            )

        # ── Step C.3 — hybrid search + decision ─────────────────────────────
        decisions: dict[str, tuple[HybridCandidate | None, str, float | None, list[dict]]] = {}
        if on_progress:
            await on_progress(f"{group_prefix}: ФЕР-поиск 0/{len(to_match)}…")
        await _write_fer_detail_log(
            db,
            session,
            group=group,
            step="fer_search_start",
            message=f"{group_prefix}. Запущен ФЕР-поиск {len(to_match)} позиций.",
            meta={"items_count": len(to_match)},
        )
        for idx, it in enumerate(to_match, start=1):
            vec = embeddings.get(it.id)
            if vec is None:
                decisions[it.id] = (None, "review", None, [])
                continue
            scope = table_scope_for_item.get(it.id) or None
            try:
                candidates = await hybrid_search_candidates(
                    db,
                    normalized_text=normalized[it.id],
                    embedding_literal=format_vector(vec),
                    allowed_table_ids=scope,
                    top_k=settings.RERANK_CANDIDATE_COUNT,
                )
                candidate, source, score = await _decide_fer_match(
                    candidates,
                    original_text=search_text_for_item[it.id],
                    normalized_text=normalized[it.id],
                )
            except Exception:  # noqa: BLE001
                logger.exception("Hybrid ФЕР search failed for item %s", it.id)
                decisions[it.id] = (None, "review", None, [])
                continue
            decisions[it.id] = (candidate, source, score, _candidates_payload(candidates))
            if idx % 25 == 0 or idx == len(to_match):
                msg = f"{group_prefix}: ФЕР-поиск {idx}/{len(to_match)}…"
                if on_progress:
                    await on_progress(msg)
                await _write_fer_detail_log(
                    db,
                    session,
                    group=group,
                    step="fer_search_progress",
                    message=msg,
                    meta={"completed": idx, "total": len(to_match)},
                )

        # ── Step C.4 — fetch chosen rows' h_hour + persist on items ─────────
        chosen_row_ids = [
            c.row_id
            for (c, _s, _sc, _cands) in decisions.values()
            if c is not None and c.row_id is not None
        ]
        rows_meta = await _fer_rows_meta(db, chosen_row_ids)

        group_stats = {"matched_auto": 0, "matched_review": 0, "no_match": 0}
        for it in to_match:
            candidate, source, score, cands = decisions[it.id]
            it.fer_match_candidates = cands or None
            if candidate is None:
                stats["no_match"] += 1
                group_stats["no_match"] += 1
                it.fer_match_source = "review"
                continue

            it.fer_table_id = candidate.table_id
            it.fer_row_id = candidate.row_id
            it.fer_match_source = source
            it.fer_match_score = round(float(score), 4) if score is not None else None

            meta = rows_meta.get(candidate.row_id or -1) or {}
            h_hour = meta.get("h_hour")
            it.fer_h_hour = float(h_hour) if h_hour is not None else None

            fer_unit, multiplier = extract_fer_unit(
                meta.get("table_title"), meta.get("row_slug"), meta.get("clarification")
            )
            it.fer_unit = fer_unit
            item_unit = normalize_unit(it.unit)
            if fer_unit is not None and item_unit is not None and fer_unit == item_unit:
                it.fer_unit_multiplier = multiplier
            else:
                it.fer_unit_multiplier = None

            if source == "auto":
                stats["matched_auto"] += 1
                group_stats["matched_auto"] += 1
            else:
                stats["matched_review"] += 1
                group_stats["matched_review"] += 1

        await _write_fer_detail_log(
            db,
            session,
            group=group,
            step="group_done",
            message=(
                f"{group_prefix}. Группа завершена: авто {group_stats['matched_auto']}, "
                f"на проверку {group_stats['matched_review']}, "
                f"без совпадения {group_stats['no_match']}."
            ),
            meta=group_stats,
        )

    if on_progress:
        await on_progress(
            f"ФЕР: авто {stats['matched_auto']}, на проверку "
            f"{stats['matched_review']}, без совпадения {stats['no_match']}"
        )
    await _write_fer_detail_log(
        db,
        session,
        step="done",
        message=(
            f"Сопоставление ФЕР завершено: авто {stats['matched_auto']}, "
            f"на проверку {stats['matched_review']}, без совпадения {stats['no_match']}, "
            f"исключено {stats['excluded']}."
        ),
        meta=stats,
    )
    return stats
