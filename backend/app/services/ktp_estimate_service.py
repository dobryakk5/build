"""AI-flow «КТП по смете»: построение WBS из позиций сметы без жёсткого матчинга.

Этап 1 — ИИ строит WBS (группы технологической последовательности + работы),
нормализует имена, добавляет забытые в смете работы. Человек правит.
Этап 2 — ИИ генерит карточку КТП по каждой группе. Человек правит.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import selectinload

from app.core.clarifications import UNKNOWN_CLARIFICATION_MARKERS
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import (
    Estimate,
    EstimateBatch,
    Job,
    KtpEstimateSession,
    KtpWbsGroup,
    KtpWbsGroupDependency,
    KtpWbsItem,
)
from app.services.ktp_service import (
    _assert_batch_belongs_to_project,
    _estimate_item_type,
    _build_wt_palette,
    _format_wt_palette_for_prompt,
)
from app.services.nw_palette_service import get_palette
from app.services.openrouter_embeddings import create_chat_completion, parse_json_object

logger = logging.getLogger(__name__)

PROMPT_VERSION = "estimate-v3"

ESTIMATE_KIND_LABELS: dict[int, str] = {
    1: "Земляные грунтовые работы",
    2: "Строительство жилого помещения",
    3: "Строительство нежилого помещения",
    4: "Реконструкция нежилого помещения",
    5: "Отделка жилого помещения",
    6: "Отделка нежилого помещения",
    7: "Инженерные работы внутренние",
    8: "Инженерные работы наружные",
    9: "Ландшафтные работы",
}

FALLBACK_GROUP_TITLE = "Прочие работы сметы"
FALLBACK_SECTION_KEY = "sec_fallback_misc"
FALLBACK_DISPLAY_TITLE = "Прочие позиции сметы"
SECTION_KEY_NORMALIZATION_VERSION = "v1"
PER_GROUP_GAP_FILL_MAX_ITEMS = 3
PROJECT_GAP_FILL_MAX_DISTRIBUTED = 10
PROJECT_GAP_FILL_MAX_UNASSIGNED = 10
KTP_STAGE3_CLARIFICATION_KEY = "stage3"
LEGACY_KTP_STAGE3_CLARIFICATION_KEY = "__ktp_stage3"
MAX_PROMPT_CLARIFICATION_LINES = 80


def _normalize_section_title(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _make_section_key(index: int, normalized_title: str) -> str:
    hash_input = f"{SECTION_KEY_NORMALIZATION_VERSION}:{normalized_title}".encode("utf-8")
    short_hash = hashlib.sha1(hash_input).hexdigest()[:6]
    return f"sec_{index:04d}_{short_hash}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def _stringify_clarification_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [
            str(item).strip()
            for item in value
            if str(item).strip() and str(item).strip() not in UNKNOWN_CLARIFICATION_MARKERS
        ]
        return ", ".join(parts) if parts else None
    if isinstance(value, dict):
        answer = value.get("answer")
        if answer is not None:
            text = str(answer).strip()
            return text if text and text not in UNKNOWN_CLARIFICATION_MARKERS else None
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or None


def _format_clarification_answers_for_prompt(
    answers: Any,
    current_group_id: str | None = None,
) -> str:
    if not isinstance(answers, dict) or not answers:
        return ""

    form_lines: list[str] = []
    current_stage3_lines: list[str] = []
    other_stage3_lines: list[str] = []
    form = answers.get("form")
    if isinstance(form, dict):
        for key, value in form.items():
            if not isinstance(value, dict):
                rendered = _stringify_clarification_value(value)
                if rendered:
                    form_lines.append(f"- {key}: {rendered}")
                continue
            rendered = _stringify_clarification_value(value.get("answers"))
            question = str(value.get("question") or key).strip()
            section = str(value.get("section") or "").strip()
            label = f"{section} / {question}" if section else question
            if rendered:
                form_lines.append(f"- {label}: {rendered}")
    else:
        for key, value in answers.items():
            if key in {KTP_STAGE3_CLARIFICATION_KEY, LEGACY_KTP_STAGE3_CLARIFICATION_KEY}:
                continue
            rendered = _stringify_clarification_value(value)
            if rendered:
                form_lines.append(f"- {key}: {rendered}")

    stage3: dict[str, Any] = {}
    legacy_stage3 = answers.get(LEGACY_KTP_STAGE3_CLARIFICATION_KEY)
    if isinstance(legacy_stage3, dict):
        stage3.update(legacy_stage3)
    current_stage3 = answers.get(KTP_STAGE3_CLARIFICATION_KEY)
    if isinstance(current_stage3, dict):
        stage3.update(current_stage3)
    if isinstance(stage3, dict):
        for group_id, group_data in stage3.items():
            if not isinstance(group_data, dict):
                continue
            group_title = str(group_data.get("group_title") or "Группа КТП").strip()
            group_answers = group_data.get("answers")
            if not isinstance(group_answers, dict):
                continue
            target_lines = (
                current_stage3_lines
                if current_group_id and str(group_id) == str(current_group_id)
                else other_stage3_lines
            )
            for answer_data in group_answers.values():
                if isinstance(answer_data, dict):
                    question = str(answer_data.get("question") or "").strip()
                    answer = _stringify_clarification_value(answer_data.get("answer"))
                else:
                    question = ""
                    answer = _stringify_clarification_value(answer_data)
                if answer:
                    label = f"{group_title} — {question}" if question else group_title
                    target_lines.append(f"- {label}: {answer}")

    if current_group_id:
        lines = current_stage3_lines + form_lines + other_stage3_lines
    else:
        lines = form_lines + other_stage3_lines
    if not lines:
        return ""
    if len(lines) > MAX_PROMPT_CLARIFICATION_LINES:
        logger.warning(
            "Clarification prompt context truncated: %s -> %s lines "
            "(current_stage3=%s, form=%s, other_stage3=%s)",
            len(lines),
            MAX_PROMPT_CLARIFICATION_LINES,
            len(current_stage3_lines),
            len(form_lines),
            len(other_stage3_lines),
        )
    return "ДАННЫЕ, УЖЕ УТОЧНЕННЫЕ ПОЛЬЗОВАТЕЛЕМ:\n" + "\n".join(
        lines[:MAX_PROMPT_CLARIFICATION_LINES]
    )


def _merge_group_answers_into_batch(
    batch: EstimateBatch,
    group: KtpWbsGroup,
    answers: dict[str, str] | None,
    source: str = "user",
) -> None:
    if not answers:
        return

    payload = copy.deepcopy(batch.clarification_answers or {})
    if not isinstance(payload, dict):
        payload = {}

    legacy_stage3 = payload.pop(LEGACY_KTP_STAGE3_CLARIFICATION_KEY, None)
    existing_stage3 = payload.get(KTP_STAGE3_CLARIFICATION_KEY)
    stage3 = existing_stage3 if isinstance(existing_stage3, dict) else {}
    if isinstance(legacy_stage3, dict):
        stage3 = {**legacy_stage3, **stage3}
    payload[KTP_STAGE3_CLARIFICATION_KEY] = stage3

    question_by_key = {
        str(q.get("key")): str(q.get("label") or q.get("key") or "").strip()
        for q in (group.card_questions_json or [])
        if isinstance(q, dict) and q.get("key")
    }
    current = stage3.get(group.id) if isinstance(stage3.get(group.id), dict) else {}
    merged_answers = current.get("answers") if isinstance(current.get("answers"), dict) else {}

    for key, value in answers.items():
        answer = str(value or "").strip()
        if not answer:
            continue
        merged_answers[str(key)] = {
            "question": question_by_key.get(str(key), str(key)),
            "answer": answer,
            "source": source,
        }

    stage3[group.id] = {
        "group_title": group.title,
        "answers": merged_answers,
        "updated_at": _now().isoformat(),
    }
    batch.clarification_answers = payload
    flag_modified(batch, "clarification_answers")


async def _merge_group_answers_into_batch_with_lock(
    batch_id: str,
    group: KtpWbsGroup,
    answers: dict[str, str] | None,
    source: str = "user",
) -> dict | None:
    if not answers:
        return None

    async with AsyncSessionLocal() as merge_db:
        locked_batch = await merge_db.scalar(
            select(EstimateBatch)
            .where(EstimateBatch.id == batch_id)
            .with_for_update()
        )
        if not locked_batch:
            return None

        _merge_group_answers_into_batch(locked_batch, group, answers, source=source)
        await merge_db.commit()
        await merge_db.refresh(locked_batch)
        return locked_batch.clarification_answers


async def _load_source_estimates_for_items(
    db: AsyncSession, items: list[KtpWbsItem]
) -> list[Estimate]:
    estimate_ids = [it.estimate_id for it in items if it.estimate_id]
    if not estimate_ids:
        return []

    rows = list(
        await db.scalars(
            select(Estimate)
            .where(Estimate.id.in_(estimate_ids))
            .where(Estimate.deleted_at.is_(None))
            .order_by(Estimate.row_order, Estimate.id)
        )
    )
    by_id = {row.id: row for row in rows}
    ordered: list[Estimate] = []
    for estimate_id in estimate_ids:
        row = by_id.get(estimate_id)
        if row and row not in ordered:
            ordered.append(row)
    return ordered


def _format_estimate_rows_for_prompt(estimates: list[Estimate]) -> str:
    if not estimates:
        return ""

    lines: list[str] = []
    for idx, estimate in enumerate(estimates[:80], start=1):
        qty = (
            f"{float(estimate.quantity):.3f} {estimate.unit or ''}".strip()
            if estimate.quantity is not None
            else estimate.unit or "—"
        )
        parts = [
            f"{idx}. {estimate.work_name}",
            f"объем: {qty}",
        ]
        if estimate.section:
            parts.append(f"раздел: {estimate.section}")
        if estimate.fer_group_title:
            parts.append(f"ФЕР-группа: {estimate.fer_group_title}")
        if estimate.fer_group_collection_name:
            parts.append(f"сборник: {estimate.fer_group_collection_name}")
        if estimate.materials:
            material_names = [
                str(item.get("name") or item.get("material") or "").strip()
                for item in estimate.materials[:8]
                if isinstance(item, dict)
            ]
            material_names = [name for name in material_names if name]
            if material_names:
                parts.append(f"материалы: {', '.join(material_names)}")
        if isinstance(estimate.raw_data, dict):
            raw_parts = []
            for key in ("code", "cipher", "description", "comment", "note"):
                value = estimate.raw_data.get(key)
                if value:
                    raw_parts.append(f"{key}: {value}")
            if raw_parts:
                parts.append("; ".join(raw_parts[:3]))
        lines.append(" | ".join(parts))

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА / ДОСТУП
# ─────────────────────────────────────────────────────────────────────────────

async def _load_work_estimates(
    db: AsyncSession, project_id: str, estimate_batch_id: str
) -> list[Estimate]:
    rows = await db.scalars(
        select(Estimate)
        .where(Estimate.project_id == project_id)
        .where(Estimate.estimate_batch_id == estimate_batch_id)
        .where(Estimate.deleted_at.is_(None))
        .order_by(Estimate.row_order, Estimate.id)
    )
    return [e for e in rows if _estimate_item_type(e) == "work"]


async def get_session(
    db: AsyncSession, project_id: str, estimate_batch_id: str
) -> KtpEstimateSession | None:
    return await db.scalar(
        select(KtpEstimateSession)
        .where(KtpEstimateSession.project_id == project_id)
        .where(KtpEstimateSession.estimate_batch_id == estimate_batch_id)
    )


async def reset_session(
    db: AsyncSession, project_id: str, session_id: str
) -> None:
    session = await get_session_by_id(db, project_id, session_id)
    await db.delete(session)
    await db.commit()


async def get_session_by_id(
    db: AsyncSession, project_id: str, session_id: str
) -> KtpEstimateSession:
    session = await db.scalar(
        select(KtpEstimateSession)
        .where(KtpEstimateSession.id == session_id)
        .where(KtpEstimateSession.project_id == project_id)
    )
    if not session:
        raise ValueError(f"Сеанс КТП {session_id} не найден в проекте {project_id}")
    return session


async def get_wbs(db: AsyncSession, project_id: str, session_id: str) -> dict[str, Any]:
    session = await get_session_by_id(db, project_id, session_id)
    groups = list(
        await db.scalars(
            select(KtpWbsGroup)
            .where(KtpWbsGroup.session_id == session_id)
            .options(selectinload(KtpWbsGroup.items))
            .order_by(KtpWbsGroup.sort_order, KtpWbsGroup.created_at)
        )
    )
    group_ids = [g.id for g in groups]
    deps = (
        list(
            await db.scalars(
                select(KtpWbsGroupDependency).where(
                    KtpWbsGroupDependency.group_id.in_(group_ids)
                )
            )
        )
        if group_ids
        else []
    )
    return {"session": session, "groups": groups, "group_dependencies": deps}


async def _get_group(
    db: AsyncSession, project_id: str, group_id: str
) -> KtpWbsGroup:
    group = await db.scalar(
        select(KtpWbsGroup)
        .where(KtpWbsGroup.id == group_id)
        .where(KtpWbsGroup.project_id == project_id)
        .options(selectinload(KtpWbsGroup.items))
    )
    if not group:
        raise ValueError(f"Группа WBS {group_id} не найдена в проекте {project_id}")
    return group


async def _get_item(
    db: AsyncSession, project_id: str, item_id: str
) -> KtpWbsItem:
    item = await db.scalar(
        select(KtpWbsItem)
        .join(KtpWbsGroup, KtpWbsItem.group_id == KtpWbsGroup.id)
        .where(KtpWbsItem.id == item_id)
        .where(KtpWbsGroup.project_id == project_id)
    )
    if not item:
        raise ValueError(f"Работа WBS {item_id} не найдена в проекте {project_id}")
    return item


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 1 — ЗАПУСК JOB
# ─────────────────────────────────────────────────────────────────────────────

async def start_stage1_job(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
    user_id: str,
    force: bool = False,
) -> tuple[Job | None, KtpEstimateSession]:
    """Запускает этап 1. Возвращает (job | None, session).

    job=None — сеанс уже существует (без force), новый прогон не нужен.
    """
    await _assert_batch_belongs_to_project(db, project_id, estimate_batch_id)

    existing = await get_session(db, project_id, estimate_batch_id)
    if existing and not force:
        return None, existing
    if existing and force:
        await db.delete(existing)
        await db.flush()

    session = KtpEstimateSession(
        project_id=project_id,
        estimate_batch_id=estimate_batch_id,
        status="stage1_pending",
    )
    db.add(session)
    try:
        await db.flush()
    except IntegrityError:
        # race при double-click — возвращаем уже созданный сеанс
        await db.rollback()
        existing = await get_session(db, project_id, estimate_batch_id)
        if existing:
            return None, existing
        raise

    job = Job(
        id=_uuid(),
        type="ktp_estimate_stage1",
        status="pending",
        project_id=project_id,
        created_by=user_id,
        input={"session_id": session.id},
    )
    db.add(job)
    # Сначала INSERT Job, чтобы FK ktp_estimate_sessions.stage1_job_id
    # был валиден при последующем UPDATE сессии.
    await db.flush()
    session.stage1_job_id = job.id
    await db.commit()
    await db.refresh(session)

    asyncio.create_task(_process_stage1(job.id))
    return job, session


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 1 — ФОНОВАЯ ОБРАБОТКА
# ─────────────────────────────────────────────────────────────────────────────

async def _process_stage1(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        session_id = job.input.get("session_id")
        session = await db.get(KtpEstimateSession, session_id)
        if not session:
            return

        job.status = "processing"
        job.started_at = datetime.utcnow()
        session.status = "stage1_processing"
        await db.commit()

        async def _progress(msg: str) -> None:
            job.result = {"_progress": msg}
            await db.commit()

        try:
            batch = await db.get(EstimateBatch, session.estimate_batch_id)
            estimates = await _load_work_estimates(
                db, session.project_id, session.estimate_batch_id
            )
            if not estimates:
                raise ValueError("В блоке сметы нет строк работ для построения КТП")

            await _progress(f"Загружено {len(estimates)} позиций сметы, запускаем ИИ…")

            # row_key -> estimate
            row_keys: dict[str, Estimate] = {
                f"R{idx:03d}": est for idx, est in enumerate(estimates, start=1)
            }

            wt_palette = _build_wt_palette(
                await get_palette(db, batch.estimate_kind)
            )
            kind_label = ESTIMATE_KIND_LABELS.get(
                batch.estimate_kind, "Строительные работы"
            )

            diagnostics: dict[str, Any] = {}
            raw_groups = await _run_stage1_ai(
                estimates,
                row_keys,
                wt_palette,
                kind_label,
                batch.clarification_answers,
                _progress,
                diagnostics,
            )

            await _progress("Сохраняем структуру работ…")
            groups, items, coverage_warnings = _materialize_wbs(
                session, raw_groups, row_keys
            )
            for g in groups:
                db.add(g)
            for it in items:
                db.add(it)

            # хвостовые предупреждения по битым чанкам ИИ
            chunk_errors = diagnostics.get("chunk_errors") or []
            warnings_out = list(coverage_warnings)
            for err in chunk_errors:
                warnings_out.append(
                    f"ИИ-сбой на блоке {err['chunk']}: {err['error']} "
                    f"(позиции попали в «{FALLBACK_GROUP_TITLE}»)"
                )

            session.stage1_raw_json = {
                "groups": raw_groups,
                "chunk_errors": chunk_errors,
                "raw_samples": diagnostics.get("raw_samples") or [],
                "coverage": diagnostics.get("coverage") or [],
                "wt_code_conflicts": diagnostics.get("wt_code_conflicts") or [],
                "gap_fill_trimmed": diagnostics.get("gap_fill_trimmed") or [],
                "repeated_sections": diagnostics.get("repeated_sections") or [],
                "unassigned_ai_items": diagnostics.get("unassigned_ai_items") or [],
            }
            session.llm_model = settings.KTP_GENERATION_MODEL
            session.prompt_version = PROMPT_VERSION
            session.status = "stage1_review"
            session.error_message = None

            ai_added = sum(1 for it in items if it.origin == "ai_added")
            job.status = "done"
            job.result = {
                "session_id": session.id,
                "group_count": len(groups),
                "item_count": len(items),
                "ai_added_count": ai_added,
                "coverage_warnings": warnings_out,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("KTP estimate stage1 failed for job %s", job_id)
            job.status = "failed"
            job.result = {"error": str(exc)}
            session.status = "stage1_failed"
            session.error_message = str(exc)
        finally:
            job.finished_at = datetime.utcnow()
            await db.commit()


async def _run_stage1_ai(
    estimates: list[Estimate],
    row_keys: dict[str, Estimate],
    wt_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Возвращает канонический список групп {title, sort_order, wt_code, items:[…]}.

    Если у сметы есть `Estimate.section` — backend строит группы сам, LLM их не
    меняет. Если ни одна строка не имеет section — fallback на старый промпт,
    где LLM группирует по технологической последовательности.
    """
    if diagnostics is None:
        diagnostics = {}
    diagnostics.setdefault("chunk_errors", [])
    diagnostics.setdefault("raw_samples", [])
    diagnostics.setdefault("coverage", [])
    diagnostics.setdefault("wt_code_conflicts", [])
    diagnostics.setdefault("gap_fill_trimmed", [])
    diagnostics.setdefault("repeated_sections", [])
    diagnostics.setdefault("unassigned_ai_items", [])

    estimate_to_row_key = {est.id: row_key for row_key, est in row_keys.items()}

    python_groups = _build_python_groups(estimates, estimate_to_row_key, diagnostics)
    ungrouped_rows = python_groups.pop("__ungrouped__", None)

    has_real_sections = bool(python_groups)
    has_ungrouped = bool(ungrouped_rows and ungrouped_rows["rows"])

    if not has_real_sections:
        diagnostics["chunk_errors"].append(
            {"chunk": "no_sections", "error": "В смете не заполнены разделы — используем legacy-промпт"}
        )
        return await _run_stage1_legacy(
            row_keys, wt_palette, kind_label, clarification_answers, on_progress, diagnostics
        )

    if has_ungrouped:
        if on_progress:
            await on_progress(
                f"Распределяем {len(ungrouped_rows['rows'])} позиций без раздела…"
            )
        await _run_ungrouped_pass(
            ungrouped_rows["rows"],
            python_groups,
            wt_palette,
            kind_label,
            clarification_answers,
            diagnostics,
        )

    await _run_section_clean_pass(
        python_groups,
        wt_palette,
        kind_label,
        clarification_answers,
        on_progress,
        diagnostics,
    )

    gap_fill_enabled = bool(getattr(settings, "KTP_STAGE1_GAP_FILL_ENABLED", True))
    if gap_fill_enabled:
        if getattr(settings, "KTP_STAGE1_PER_GROUP_GAP_FILL_ENABLED", True):
            if on_progress:
                await on_progress("Проверяем полноту работ внутри групп…")
            await _run_per_group_gap_fill(python_groups, kind_label, clarification_answers, diagnostics)
        if getattr(settings, "KTP_STAGE1_PROJECT_GAP_FILL_ENABLED", True):
            if on_progress:
                await on_progress("Проверяем полноту проекта…")
            await _run_project_gap_fill(
                python_groups, kind_label, clarification_answers, diagnostics
            )

    return _assemble_canonical_groups(python_groups, row_keys, diagnostics)


def _build_python_groups(
    estimates: list[Estimate],
    estimate_to_row_key: dict[str, str],
    diagnostics: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """A: backend строит группы по Estimate.section.

    Возвращает dict[section_key | "__ungrouped__"] = {
        section_key, display_title, rows: [(row_key, est), …], sort_order: int
    }
    Повторяющиеся секции (одинаковый normalized_title) сливаются.
    """
    groups: dict[str, dict[str, Any]] = {}
    title_to_section_key: dict[str, str] = {}
    next_index = 1

    for est in sorted(estimates, key=lambda e: (e.row_order or 0, e.id)):
        row_key = estimate_to_row_key.get(est.id)
        if not row_key:
            continue
        normalized = _normalize_section_title(est.section)
        if not normalized:
            bucket = groups.setdefault(
                "__ungrouped__",
                {
                    "section_key": "__ungrouped__",
                    "display_title": "",
                    "rows": [],
                    "sort_order": float("inf"),
                },
            )
            bucket["rows"].append((row_key, est))
            continue

        existing_key = title_to_section_key.get(normalized)
        if existing_key:
            bucket = groups[existing_key]
            bucket["rows"].append((row_key, est))
            diagnostics["repeated_sections"].append(
                {
                    "normalized_title": normalized,
                    "section_key": existing_key,
                    "first_row_order": bucket["sort_order"],
                    "repeated_row_order": int(est.row_order or 0),
                }
            )
            continue

        section_key = _make_section_key(next_index, normalized)
        next_index += 1
        title_to_section_key[normalized] = section_key
        groups[section_key] = {
            "section_key": section_key,
            "display_title": str(est.section).strip(),
            "rows": [(row_key, est)],
            "sort_order": int(est.row_order or 0),
        }

    return groups


# ─────────────────────────────────────────────────────────────────────────────
# ЛОКАЛЬНЫЙ ХЕЛПЕР ВЫЗОВА LLM
# ─────────────────────────────────────────────────────────────────────────────

async def _call_stage1(prompt: str) -> str:
    return await create_chat_completion(
        model=settings.KTP_GENERATION_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты эксперт-технолог в строительстве. Строишь WBS из "
                    "строительной сметы. Возвращаешь СТРОГО валидный JSON: "
                    "без markdown, без комментариев, без trailing commas, "
                    "все строки в двойных кавычках."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=settings.KTP_ESTIMATE_MAX_TOKENS,
        response_format={"type": "json_object"},
    )


async def _call_and_capture(
    prompt: str,
    label: str,
    diagnostics: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    raw = ""
    try:
        raw = await _call_stage1(prompt)
        return _parse_json_response(raw), None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stage1 LLM call failed: %s", label)
        diagnostics["chunk_errors"].append({"chunk": label, "error": str(exc)})
        if raw:
            diagnostics["raw_samples"].append(raw[:2000])
        return None, str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# ПАРСЕРЫ И ВАЛИДАТОРЫ ФОРМАТА
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> dict[str, Any]:
    parsed = parse_json_object(raw)
    if not isinstance(parsed, dict):
        raise ValueError("LLM вернул не JSON-объект")
    return parsed


def _validate_section_response(parsed: dict[str, Any]) -> dict[str, Any]:
    items_raw = parsed.get("items")
    if not isinstance(items_raw, list):
        raise ValueError("section-call: нет списка items")
    cleaned_title = str(parsed.get("cleaned_title") or "").strip() or None
    wt_code = parsed.get("wt_code")
    wt_code = str(wt_code).strip().upper() if isinstance(wt_code, str) and wt_code.strip() else None
    items: list[dict[str, Any]] = []
    for raw_it in items_raw:
        if not isinstance(raw_it, dict):
            continue
        row_key = raw_it.get("row_key")
        if not isinstance(row_key, str) or not row_key.strip():
            continue
        name = str(raw_it.get("name") or "").strip()
        items.append({"row_key": row_key.strip(), "name": name})
    return {"cleaned_title": cleaned_title, "wt_code": wt_code, "items": items}


def _validate_ungrouped_response(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    raw_list = parsed.get("assignments")
    if not isinstance(raw_list, list):
        raise ValueError("__ungrouped__-call: нет списка assignments")
    out: list[dict[str, Any]] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        row_key = raw.get("row_key")
        if not isinstance(row_key, str) or not row_key.strip():
            continue
        section_key = raw.get("assigned_section_key")
        if not isinstance(section_key, str) or not section_key.strip():
            section_key = None
        else:
            section_key = section_key.strip()
        name = str(raw.get("name") or "").strip() or None
        out.append({"row_key": row_key.strip(), "assigned_section_key": section_key, "name": name})
    return out


def _validate_per_group_gap_fill_response(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    raw_list = parsed.get("added_items")
    if not isinstance(raw_list, list):
        raise ValueError("per-group gap-fill: нет списка added_items")
    out: list[dict[str, Any]] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        reason = str(raw.get("ai_reason") or "").strip()
        if not name or not reason:
            continue
        out.append({"name": name, "ai_reason": reason})
    return out


def _validate_project_gap_fill_response(parsed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    distributed_raw = parsed.get("distributed") or []
    unassigned_raw = parsed.get("unassigned") or []
    if not isinstance(distributed_raw, list) or not isinstance(unassigned_raw, list):
        raise ValueError("project gap-fill: distributed/unassigned должны быть списками")
    distributed: list[dict[str, Any]] = []
    for raw in distributed_raw:
        if not isinstance(raw, dict):
            continue
        group_key = raw.get("group_key")
        name = str(raw.get("name") or "").strip()
        reason = str(raw.get("ai_reason") or "").strip()
        if not name or not reason or not isinstance(group_key, str) or not group_key.strip():
            continue
        distributed.append(
            {"group_key": group_key.strip(), "name": name, "ai_reason": reason}
        )
    unassigned: list[dict[str, Any]] = []
    for raw in unassigned_raw:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        reason = str(raw.get("ai_reason") or "").strip()
        if not name or not reason:
            continue
        unassigned.append({"name": name, "ai_reason": reason})
    return {"distributed": distributed, "unassigned": unassigned}


# Legacy совместимость для no_sections fallback и старых тестов.
def _parse_stage1_response(raw: str) -> list[dict[str, Any]]:
    parsed = parse_json_object(raw)
    groups = parsed.get("groups")
    if not isinstance(groups, list):
        raise ValueError("LLM вернул ответ без списка groups")
    return [g for g in groups if isinstance(g, dict)]


_parse_legacy_groups_response = _parse_stage1_response


# ─────────────────────────────────────────────────────────────────────────────
# ВАЛИДАТОРЫ ПОКРЫТИЯ
# ─────────────────────────────────────────────────────────────────────────────

def _validate_section_coverage(
    *,
    items: list[dict[str, Any]],
    section_rows: list[tuple[str, Estimate]],
    section_key: str,
    chunk_label: str,
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_by_key = {row_key: est for row_key, est in section_rows}
    expected = set(expected_by_key.keys())
    seen: set[str] = set()
    unknown: list[str] = []
    duplicates: list[str] = []
    cleaned: list[dict[str, Any]] = []

    for it in items:
        row_key = it.get("row_key")
        if not isinstance(row_key, str):
            continue
        if row_key not in expected:
            unknown.append(row_key)
            continue
        if row_key in seen:
            duplicates.append(row_key)
            continue
        seen.add(row_key)
        est = expected_by_key[row_key]
        name = it.get("name") or est.work_name
        cleaned.append(
            {
                "name": str(name).strip() or est.work_name,
                "origin": "from_estimate",
                "row_key": row_key,
            }
        )

    missing = sorted(expected - seen)
    for row_key in missing:
        est = expected_by_key[row_key]
        cleaned.append(
            {
                "name": est.work_name,
                "origin": "from_estimate",
                "row_key": row_key,
            }
        )

    if unknown or duplicates or missing:
        diagnostics["coverage"].append(
            {
                "kind": "section",
                "section_key": section_key,
                "chunk": chunk_label,
                "unknown": unknown,
                "duplicated": duplicates,
                "missing": missing,
            }
        )
    return cleaned


def _validate_ungrouped_coverage(
    *,
    assignments: list[dict[str, Any]],
    orphan_rows: list[tuple[str, Estimate]],
    valid_section_keys: set[str],
    diagnostics: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[tuple[str, Estimate]]]:
    """Возвращает (cleaned_assignments, fallback_rows).

    fallback_rows — orphan-строки, для которых LLM не дал валидного section_key
    (или вообще пропустил), их кладём в FALLBACK группу.
    """
    expected_by_key = {row_key: est for row_key, est in orphan_rows}
    expected = set(expected_by_key.keys())
    seen: set[str] = set()
    unknown: list[str] = []
    duplicates: list[str] = []
    invalid: list[str] = []
    cleaned: list[dict[str, Any]] = []

    for a in assignments:
        row_key = a.get("row_key")
        if not isinstance(row_key, str):
            continue
        if row_key not in expected:
            unknown.append(row_key)
            continue
        if row_key in seen:
            duplicates.append(row_key)
            continue
        seen.add(row_key)
        section_key = a.get("assigned_section_key")
        if not section_key or section_key not in valid_section_keys:
            invalid.append(row_key)
            continue
        est = expected_by_key[row_key]
        cleaned.append(
            {
                "row_key": row_key,
                "assigned_section_key": section_key,
                "name": (a.get("name") or est.work_name).strip() or est.work_name,
            }
        )

    fallback_keys = (expected - seen) | set(invalid)
    fallback_rows = [
        (row_key, expected_by_key[row_key]) for row_key in sorted(fallback_keys)
    ]

    if unknown or duplicates or invalid or (expected - seen - set(invalid)):
        diagnostics["coverage"].append(
            {
                "kind": "ungrouped",
                "unknown": unknown,
                "duplicated": duplicates,
                "missing": sorted(expected - seen - set(invalid)),
                "invalid_assignment": invalid,
            }
        )
    return cleaned, fallback_rows


# ─────────────────────────────────────────────────────────────────────────────
# СБОРЩИКИ ПРОМПТОВ
# ─────────────────────────────────────────────────────────────────────────────

def _format_rows_for_prompt(rows: list[tuple[str, Estimate]]) -> str:
    lines: list[str] = []
    for key, est in rows:
        qty = (
            f"{float(est.quantity):.2f} {est.unit or ''}".strip()
            if est.quantity is not None
            else "—"
        )
        price = (
            f"{float(est.total_price):.0f} руб."
            if est.total_price is not None
            else "—"
        )
        lines.append(f"  {key} | {est.work_name} | {qty} | {price}")
    return "\n".join(lines)


def _build_section_prompt(
    *,
    kind_label: str,
    display_title: str,
    rows: list[tuple[str, Estimate]],
    wt_palette: list[dict[str, Any]],
    clarification_answers: dict | None,
) -> str:
    palette_block = _format_wt_palette_for_prompt(wt_palette) or "(палитра пуста)"
    rows_block = _format_rows_for_prompt(rows)
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    return f"""Тип объекта: {kind_label}
Группа работ (из сметы): «{display_title}»

ПАЛИТРА WT (выбери ОДИН код для этой группы):
{palette_block}
{clarification_section}

ПОЗИЦИИ ЭТОЙ ГРУППЫ (row_key | наименование | объём | стоимость):
{rows_block}

ЗАДАЧА:
1. НЕ создавай новых групп и НЕ перераспределяй позиции — все они принадлежат
   именно этой группе.
2. Если в названии группы явная опечатка/неаккуратное оформление (точка в конце,
   нижний регистр, лишние пробелы), верни очищенный вариант в "cleaned_title".
   Сохраняй смысл; не меняй существительное на синоним.
3. Подбери ОДИН wt_code из палитры, наиболее подходящий всей группе.
4. Для КАЖДОГО row_key из списка верни запись с этим row_key и нормализованным
   "name" (убрать сокращения и опечатки). НЕ объединяй похожие позиции,
   НЕ удаляй ничего — исходные строки сметы должны вернуться все.

Верни строго JSON без markdown:
{{
  "cleaned_title": "Кровля",
  "wt_code": "WT-12",
  "items": [
    {{"row_key": "R007", "name": "Монтаж стропильной системы"}}
  ]
}}"""


def _build_ungrouped_prompt(
    *,
    kind_label: str,
    available_groups: list[dict[str, str]],
    rows: list[tuple[str, Estimate]],
    clarification_answers: dict | None,
) -> str:
    groups_block = json.dumps(available_groups, ensure_ascii=False, indent=2)
    rows_block = _format_rows_for_prompt(rows)
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    return f"""Тип объекта: {kind_label}

ДОСТУПНЫЕ ГРУППЫ (используй только эти section_key):
{groups_block}
{clarification_section}

СТРОКИ БЕЗ РАЗДЕЛА (row_key | наименование | объём | стоимость):
{rows_block}

ЗАДАЧА:
1. Раскидай каждую строку в одну из доступных групп. assigned_section_key
   ДОЛЖЕН строго совпадать с одним из section_key выше.
2. Если строка не подходит ни к одной группе — верни assigned_section_key: null.
3. Не выдумывай новые section_key.

Верни строго JSON без markdown:
{{"assignments": [
  {{"row_key": "R042", "assigned_section_key": "sec_0001_a8f31c", "name": "..."}}
]}}"""


def _build_per_group_gap_fill_prompt(
    *,
    kind_label: str,
    display_title: str,
    items: list[dict[str, Any]],
    clarification_answers: dict | None,
) -> str:
    items_block = "\n".join(f"- {it['name']}" for it in items) or "(пусто)"
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    return f"""Тип объекта: {kind_label}
Группа работ: «{display_title}»

РАБОТЫ В ГРУППЕ:
{items_block}
{clarification_section}

ЗАДАЧА:
1. Определи, каких работ ВНУТРИ ИМЕННО ЭТОЙ ГРУППЫ технологически не хватает,
   чтобы её можно было выполнить.
2. Верни не более {PER_GROUP_GAP_FILL_MAX_ITEMS} пунктов. Пустой список — норма.
3. Каждая запись обязательно содержит "ai_reason" с короткой причиной.
4. Не добавляй работы из других групп.

Верни строго JSON без markdown:
{{"added_items": [
  {{"name": "Снегозадержатели", "ai_reason": "обязательная защита кровли"}}
]}}"""


def _build_project_gap_fill_prompt(
    *,
    kind_label: str,
    available_groups: list[dict[str, str]],
    clarification_answers: dict | None,
) -> str:
    groups_block = json.dumps(available_groups, ensure_ascii=False, indent=2)
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    return f"""Тип объекта: {kind_label}

ДОСТУПНЫЕ ГРУППЫ (по group_key):
{groups_block}
{clarification_section}

ЗАДАЧА:
1. Опираясь на состав проекта и ответы пользователя, предложи технологически
   обязательные работы, которых в проекте НЕТ вообще (демонтаж, пусконаладка,
   вывоз мусора, благоустройство и т.п.).
2. Постарайся распределить такие работы в ИМЕЮЩИЕСЯ группы по group_key.
3. Если работа не подходит ни к одной группе — помести её в "unassigned".
4. Не более {PROJECT_GAP_FILL_MAX_DISTRIBUTED} записей в distributed
   и не более {PROJECT_GAP_FILL_MAX_UNASSIGNED} в unassigned.
5. У каждой записи обязательно "ai_reason".

Верни строго JSON без markdown:
{{
  "distributed": [
    {{"group_key": "sec_0001_a8f31c", "name": "Снегозадержатели",
      "ai_reason": "обязательная защита кровли"}}
  ],
  "unassigned": [
    {{"name": "Пусконаладка отопления", "ai_reason": "запрошено заказчиком"}}
  ]
}}"""


# Legacy prompt (используется в no_sections fallback и в существующем тесте).
def _build_stage1_prompt(
    rows: list[tuple[str, Estimate]],
    wt_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None = None,
    gap_fill: bool = False,
) -> str:
    rows_block = _format_rows_for_prompt(rows)
    palette_block = _format_wt_palette_for_prompt(wt_palette) or "(палитра пуста)"
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    gap_instruction = (
        "7. Добавь технологически необходимые работы, которые ОТСУТСТВУЮТ в "
        "смете, но обязательны для этого типа объекта (подготовительные, "
        "демонтаж, пусконаладка, вывоз мусора, благоустройство). Помечай их "
        '"origin": "ai_added" и заполняй "ai_reason".'
        if gap_fill
        else "7. НЕ добавляй работы, которых нет в списке позиций — только "
        "группируй и нормализуй переданные позиции."
    )

    return f"""Тип объекта: {kind_label}

СПРАВОЧНО (необязательная подсказка по категориям WT — учитывай, но не обязан
привязывать каждую работу; свободная категоризация разрешена):
{palette_block}
{clarification_section}

ПОЗИЦИИ СМЕТЫ (row_key | наименование | объём | стоимость):
{rows_block}

ЗАДАЧА:
1. Сгруппируй позиции в группы по технологической последовательности
   выполнения (подготовительные → земляные → фундаменты → ... → отделка).
2. Не дроби структуру на слишком много КТП. Одна группа должна быть крупным
   технологическим блоком, по которому реально удобно выпускать одну КТП:
   собирай вместе виды работ, относящиеся к одному типу работ, одной зоне
   технологии и одному организационному этапу. Не создавай отдельную группу
   для каждой строки сметы, материала, мелкой операции или разновидности
   одной и той же работы.
3. Разделяй группы только когда меняется технология выполнения, зона
   ответственности, последовательный этап или требуются принципиально разные
   меры контроля и безопасности.
4. Внутри каждой группы укажи работы; нормализуй неаккуратные наименования.
5. Объедини дубли и однотипные позиции.
6. Для каждой работы из сметы укажи "origin": "from_estimate" и её "row_key".
{gap_instruction}

Верни строго JSON без markdown:
{{"groups": [
  {{"title": "Земляные работы", "sort_order": 1, "wt_code": "WT-01",
    "items": [
      {{"name": "Разработка грунта экскаватором", "origin": "from_estimate",
       "row_key": "R004", "ai_reason": "нормализовано из 'разраб. грунта'"}},
      {{"name": "Обратная засыпка пазух", "origin": "ai_added",
       "ai_reason": "требуется после устройства фундамента, в смете нет"}}
    ]}}
]}}"""


# ─────────────────────────────────────────────────────────────────────────────
# ШАГИ ПАЙПЛАЙНА
# ─────────────────────────────────────────────────────────────────────────────

async def _run_ungrouped_pass(
    orphan_rows: list[tuple[str, Estimate]],
    python_groups: dict[str, dict[str, Any]],
    wt_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    diagnostics: dict[str, Any],
) -> None:
    """B: распределяет orphan-строки в python_groups по section_key.

    Не подошедшие → создают/пополняют FALLBACK-группу.
    """
    available = [
        {"section_key": grp["section_key"], "title": grp["display_title"]}
        for grp in python_groups.values()
    ]
    prompt = _build_ungrouped_prompt(
        kind_label=kind_label,
        available_groups=available,
        rows=orphan_rows,
        clarification_answers=clarification_answers,
    )
    parsed, err = await _call_and_capture(prompt, "__ungrouped__", diagnostics)
    if parsed is None or err:
        # LLM полностью провалился — все orphan-строки уходят в fallback.
        _push_to_fallback(orphan_rows, python_groups)
        return

    try:
        assignments_raw = _validate_ungrouped_response(parsed)
    except Exception as exc:  # noqa: BLE001
        diagnostics["chunk_errors"].append(
            {"chunk": "__ungrouped__/validate", "error": str(exc)}
        )
        _push_to_fallback(orphan_rows, python_groups)
        return

    valid_keys = {grp["section_key"] for grp in python_groups.values()}
    cleaned, fallback_rows = _validate_ungrouped_coverage(
        assignments=assignments_raw,
        orphan_rows=orphan_rows,
        valid_section_keys=valid_keys,
        diagnostics=diagnostics,
    )
    rows_by_key = {row_key: est for row_key, est in orphan_rows}
    for a in cleaned:
        target = python_groups[a["assigned_section_key"]]
        est = rows_by_key[a["row_key"]]
        target["rows"].append((a["row_key"], est))
    if fallback_rows:
        _push_to_fallback(fallback_rows, python_groups)


def _push_to_fallback(
    rows: list[tuple[str, Estimate]],
    python_groups: dict[str, dict[str, Any]],
) -> None:
    bucket = python_groups.get(FALLBACK_SECTION_KEY)
    if not bucket:
        sort_order = min((int(est.row_order or 0) for _, est in rows), default=10**9)
        bucket = {
            "section_key": FALLBACK_SECTION_KEY,
            "display_title": FALLBACK_DISPLAY_TITLE,
            "rows": [],
            "sort_order": sort_order,
        }
        python_groups[FALLBACK_SECTION_KEY] = bucket
    bucket["rows"].extend(rows)
    bucket["sort_order"] = min(
        bucket["sort_order"], min((int(est.row_order or 0) for _, est in rows), default=10**9)
    )


async def _run_section_clean_pass(
    python_groups: dict[str, dict[str, Any]],
    wt_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    on_progress: Callable[[str], Awaitable[None]] | None,
    diagnostics: dict[str, Any],
) -> None:
    """C: per-section clean-only LLM-вызов. Заполняет grp['cleaned_items'] и grp['wt_code']."""
    chunk_size = max(20, int(settings.KTP_ESTIMATE_CHUNK_ROWS))
    sections_ordered = sorted(python_groups.values(), key=lambda g: g["sort_order"])
    total = len(sections_ordered)

    for idx, grp in enumerate(sections_ordered, start=1):
        rows = grp["rows"]
        if not rows:
            grp["cleaned_items"] = []
            grp["wt_code"] = None
            grp["cleaned_title"] = grp["display_title"]
            continue

        if on_progress:
            await on_progress(
                f"ИИ чистит группу «{grp['display_title']}» ({idx}/{total}, {len(rows)} позиций)…"
            )

        chunks = [rows[i : i + chunk_size] for i in range(0, len(rows), chunk_size)]
        all_items: list[dict[str, Any]] = []
        wt_code_votes: list[str] = []
        cleaned_title: str | None = None

        for c_idx, chunk in enumerate(chunks, start=1):
            chunk_label = (
                f"section/{grp['section_key']}/chunk-{c_idx}/{len(chunks)}"
                if len(chunks) > 1
                else f"section/{grp['section_key']}"
            )
            prompt = _build_section_prompt(
                kind_label=kind_label,
                display_title=grp["display_title"],
                rows=chunk,
                wt_palette=wt_palette,
                clarification_answers=clarification_answers,
            )
            parsed, err = await _call_and_capture(prompt, chunk_label, diagnostics)
            if parsed is None or err:
                # ИИ упал на этом чанке — кладём строки как есть, чистка не выполнена.
                fallback_items = _validate_section_coverage(
                    items=[],
                    section_rows=chunk,
                    section_key=grp["section_key"],
                    chunk_label=chunk_label,
                    diagnostics=diagnostics,
                )
                all_items.extend(fallback_items)
                continue

            try:
                validated = _validate_section_response(parsed)
            except Exception as exc:  # noqa: BLE001
                diagnostics["chunk_errors"].append(
                    {"chunk": f"{chunk_label}/validate", "error": str(exc)}
                )
                fallback_items = _validate_section_coverage(
                    items=[],
                    section_rows=chunk,
                    section_key=grp["section_key"],
                    chunk_label=chunk_label,
                    diagnostics=diagnostics,
                )
                all_items.extend(fallback_items)
                continue

            cleaned = _validate_section_coverage(
                items=validated["items"],
                section_rows=chunk,
                section_key=grp["section_key"],
                chunk_label=chunk_label,
                diagnostics=diagnostics,
            )
            all_items.extend(cleaned)
            if validated["wt_code"]:
                wt_code_votes.append(validated["wt_code"])
            if cleaned_title is None and validated["cleaned_title"]:
                cleaned_title = validated["cleaned_title"]

        # majority vote
        final_wt_code: str | None = None
        if wt_code_votes:
            counter = Counter(wt_code_votes)
            final_wt_code = counter.most_common(1)[0][0]
            if len(set(wt_code_votes)) > 1:
                diagnostics["wt_code_conflicts"].append(
                    {
                        "section_key": grp["section_key"],
                        "votes": dict(counter),
                        "chosen": final_wt_code,
                    }
                )

        grp["cleaned_items"] = all_items
        grp["wt_code"] = final_wt_code
        grp["cleaned_title"] = cleaned_title or grp["display_title"]


async def _run_per_group_gap_fill(
    python_groups: dict[str, dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    diagnostics: dict[str, Any],
) -> None:
    """E.1: внутри каждой группы добавляем недостающие работы (max 3)."""
    for grp in python_groups.values():
        items = grp.get("cleaned_items") or []
        if not items:
            continue
        prompt = _build_per_group_gap_fill_prompt(
            kind_label=kind_label,
            display_title=grp.get("cleaned_title") or grp["display_title"],
            items=items,
            clarification_answers=clarification_answers,
        )
        label = f"per_group_gap_fill/{grp['section_key']}"
        parsed, err = await _call_and_capture(prompt, label, diagnostics)
        if parsed is None or err:
            continue
        try:
            added = _validate_per_group_gap_fill_response(parsed)
        except Exception as exc:  # noqa: BLE001
            diagnostics["chunk_errors"].append(
                {"chunk": f"{label}/validate", "error": str(exc)}
            )
            continue
        original_count = len(added)
        added = added[:PER_GROUP_GAP_FILL_MAX_ITEMS]
        if original_count > PER_GROUP_GAP_FILL_MAX_ITEMS:
            diagnostics["gap_fill_trimmed"].append(
                {
                    "kind": "per_group",
                    "section_key": grp["section_key"],
                    "received": original_count,
                    "kept": PER_GROUP_GAP_FILL_MAX_ITEMS,
                }
            )
        gap_items = grp.setdefault("gap_items", [])
        for it in added:
            gap_items.append(
                {
                    "name": it["name"],
                    "origin": "ai_added",
                    "row_key": None,
                    "review_status": "pending",
                    "ai_reason": it["ai_reason"],
                }
            )


async def _run_project_gap_fill(
    python_groups: dict[str, dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    diagnostics: dict[str, Any],
) -> None:
    """E.2: project-wide gap-fill. Распределённое — в группы; нераспределённое — в unassigned_ai_items."""
    available = [
        {"group_key": grp["section_key"], "title": grp.get("cleaned_title") or grp["display_title"]}
        for grp in python_groups.values()
        if grp["section_key"] != FALLBACK_SECTION_KEY
    ]
    if not available:
        return
    prompt = _build_project_gap_fill_prompt(
        kind_label=kind_label,
        available_groups=available,
        clarification_answers=clarification_answers,
    )
    parsed, err = await _call_and_capture(prompt, "project_gap_fill", diagnostics)
    if parsed is None or err:
        return
    try:
        result = _validate_project_gap_fill_response(parsed)
    except Exception as exc:  # noqa: BLE001
        diagnostics["chunk_errors"].append(
            {"chunk": "project_gap_fill/validate", "error": str(exc)}
        )
        return

    valid_keys = {grp["section_key"] for grp in python_groups.values()}
    distributed = result["distributed"]
    unassigned = result["unassigned"]

    # group_key validation: невалидный → переезжает в unassigned (если есть место).
    valid_distributed: list[dict[str, Any]] = []
    for it in distributed:
        if it["group_key"] in valid_keys:
            valid_distributed.append(it)
        else:
            if len(unassigned) < PROJECT_GAP_FILL_MAX_UNASSIGNED:
                unassigned.append({"name": it["name"], "ai_reason": it["ai_reason"]})

    if len(valid_distributed) > PROJECT_GAP_FILL_MAX_DISTRIBUTED:
        diagnostics["gap_fill_trimmed"].append(
            {
                "kind": "project_distributed",
                "received": len(valid_distributed),
                "kept": PROJECT_GAP_FILL_MAX_DISTRIBUTED,
            }
        )
        valid_distributed = valid_distributed[:PROJECT_GAP_FILL_MAX_DISTRIBUTED]
    if len(unassigned) > PROJECT_GAP_FILL_MAX_UNASSIGNED:
        diagnostics["gap_fill_trimmed"].append(
            {
                "kind": "project_unassigned",
                "received": len(unassigned),
                "kept": PROJECT_GAP_FILL_MAX_UNASSIGNED,
            }
        )
        unassigned = unassigned[:PROJECT_GAP_FILL_MAX_UNASSIGNED]

    for it in valid_distributed:
        grp = python_groups[it["group_key"]]
        gap_items = grp.setdefault("gap_items", [])
        gap_items.append(
            {
                "name": it["name"],
                "origin": "ai_added",
                "row_key": None,
                "review_status": "pending",
                "ai_reason": it["ai_reason"],
            }
        )

    diagnostics["unassigned_ai_items"].extend(unassigned)


def _assemble_canonical_groups(
    python_groups: dict[str, dict[str, Any]],
    row_keys: dict[str, Estimate],
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    """F: собирает старый канонический формат {"groups": [...]} для _materialize_wbs."""
    result: list[dict[str, Any]] = []
    seen_row_keys: set[str] = set()

    for grp in sorted(python_groups.values(), key=lambda g: g["sort_order"]):
        items: list[dict[str, Any]] = []
        for it in grp.get("cleaned_items") or []:
            row_key = it.get("row_key")
            if isinstance(row_key, str):
                if row_key in seen_row_keys:
                    continue
                seen_row_keys.add(row_key)
            items.append(it)
        items.extend(grp.get("gap_items") or [])
        result.append(
            {
                "title": grp.get("cleaned_title") or grp["display_title"] or FALLBACK_DISPLAY_TITLE,
                "sort_order": float(grp["sort_order"]),
                "wt_code": grp.get("wt_code"),
                "section_key": grp["section_key"],
                "items": items,
            }
        )

    # D.3: глобальная страховка — какие row_key мы вообще нигде не покрыли.
    all_expected = set(row_keys.keys())
    global_missing = sorted(all_expected - seen_row_keys)
    global_unknown = sorted(seen_row_keys - all_expected)
    if global_missing or global_unknown:
        diagnostics["coverage"].append(
            {
                "kind": "global",
                "missing": global_missing,
                "unknown": global_unknown,
            }
        )
    if global_missing:
        fallback_items = [
            {
                "name": row_keys[row_key].work_name,
                "origin": "from_estimate",
                "row_key": row_key,
            }
            for row_key in global_missing
        ]
        result.append(
            {
                "title": FALLBACK_DISPLAY_TITLE,
                "sort_order": float(10**9),
                "wt_code": None,
                "section_key": FALLBACK_SECTION_KEY,
                "items": fallback_items,
            }
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY FALLBACK: смета без секций
# ─────────────────────────────────────────────────────────────────────────────

async def _run_stage1_legacy(
    row_keys: dict[str, Estimate],
    wt_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    on_progress: Callable[[str], Awaitable[None]] | None,
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Старое поведение: LLM группирует по технологической последовательности."""
    chunk_size = max(20, int(settings.KTP_ESTIMATE_CHUNK_ROWS))
    keys = list(row_keys.keys())

    async def _call_and_parse_legacy(prompt: str, label: str) -> tuple[list[dict[str, Any]], str | None]:
        raw = ""
        try:
            raw = await _call_stage1(prompt)
            return _parse_legacy_groups_response(raw), None
        except Exception as exc:  # noqa: BLE001
            logger.exception("Stage1 legacy chunk failed: %s", label)
            diagnostics["chunk_errors"].append({"chunk": label, "error": str(exc)})
            if raw:
                diagnostics["raw_samples"].append(raw[:2000])
            return [], str(exc)

    if len(keys) <= chunk_size:
        if on_progress:
            await on_progress(f"ИИ анализирует {len(keys)} позиций сметы (legacy)…")
        prompt = _build_stage1_prompt(
            [(k, row_keys[k]) for k in keys],
            wt_palette,
            kind_label,
            clarification_answers,
            gap_fill=True,
        )
        groups, err = await _call_and_parse_legacy(prompt, "legacy/single")
        if err and not groups:
            return []
        return groups

    total_chunks = (len(keys) + chunk_size - 1) // chunk_size
    merged: dict[str, dict[str, Any]] = {}
    order = 0
    successful_chunks = 0
    for chunk_idx, start in enumerate(range(0, len(keys), chunk_size), start=1):
        if on_progress:
            await on_progress(
                f"ИИ анализирует блок {chunk_idx}/{total_chunks} (legacy)…"
            )
        chunk = keys[start : start + chunk_size]
        prompt = _build_stage1_prompt(
            [(k, row_keys[k]) for k in chunk],
            wt_palette,
            kind_label,
            clarification_answers,
            gap_fill=False,
        )
        parsed, err = await _call_and_parse_legacy(
            prompt, f"legacy/chunk-{chunk_idx}/{total_chunks}"
        )
        if err:
            continue
        successful_chunks += 1
        for grp in parsed:
            title = str(grp.get("title") or "").strip() or FALLBACK_GROUP_TITLE
            slug = title.lower()
            bucket = merged.get(slug)
            if not bucket:
                order += 1
                bucket = {
                    "title": title,
                    "sort_order": order,
                    "wt_code": grp.get("wt_code"),
                    "items": [],
                }
                merged[slug] = bucket
            bucket["items"].extend(grp.get("items") or [])

    return list(merged.values())


def _materialize_wbs(
    session: KtpEstimateSession,
    raw_groups: list[dict[str, Any]],
    row_keys: dict[str, Estimate],
) -> tuple[list[KtpWbsGroup], list[KtpWbsItem], list[str]]:
    """Создаёт ORM-объекты + валидирует инвариант покрытия (без сирот)."""
    groups: list[KtpWbsGroup] = []
    items: list[KtpWbsItem] = []
    warnings: list[str] = []
    seen_estimate_ids: set[str] = set()

    for g_idx, raw_g in enumerate(raw_groups, start=1):
        title = str(raw_g.get("title") or "").strip() or f"Группа {g_idx}"
        try:
            sort_order = float(raw_g.get("sort_order") or g_idx)
        except (TypeError, ValueError):
            sort_order = float(g_idx)
        wt_code = raw_g.get("wt_code")
        wt_code = str(wt_code).strip().upper() if isinstance(wt_code, str) and wt_code.strip() else None

        group = KtpWbsGroup(
            id=_uuid(),
            session_id=session.id,
            project_id=session.project_id,
            title=title,
            sort_order=sort_order,
            wt_code=wt_code,
            status="draft",
        )
        groups.append(group)

        raw_items = raw_g.get("items") or []
        for i_idx, raw_it in enumerate(raw_items, start=1):
            if not isinstance(raw_it, dict):
                continue
            name = str(raw_it.get("name") or "").strip()
            if not name:
                continue
            origin = str(raw_it.get("origin") or "ai_added").strip()
            row_key = raw_it.get("row_key")
            estimate: Estimate | None = None
            if origin == "from_estimate" and isinstance(row_key, str):
                estimate = row_keys.get(row_key.strip())
            if origin == "from_estimate" and estimate is None:
                # неизвестный row_key — считаем добавленной работой
                origin = "ai_added"

            if estimate is not None:
                if estimate.id in seen_estimate_ids:
                    warnings.append(
                        f"Позиция «{estimate.work_name}» продублирована ИИ — "
                        f"оставлена одна копия"
                    )
                    continue
                seen_estimate_ids.add(estimate.id)

            items.append(
                KtpWbsItem(
                    id=_uuid(),
                    group_id=group.id,
                    session_id=session.id,
                    name=name,
                    sort_order=float(i_idx) * 1000.0,
                    origin=origin,
                    estimate_id=estimate.id if estimate else None,
                    unit=estimate.unit if estimate else None,
                    quantity=estimate.quantity if estimate else None,
                    quantity_source="estimate" if estimate else None,
                    review_status="accepted" if origin != "ai_added" else "pending",
                    ai_reason=(
                        str(raw_it.get("ai_reason")).strip()
                        if raw_it.get("ai_reason")
                        else None
                    ),
                )
            )

    # Инвариант покрытия: каждая work-строка должна попасть ровно в один item.
    missing = [
        est for est in row_keys.values() if est.id not in seen_estimate_ids
    ]
    if missing:
        warnings.append(
            f"{len(missing)} позиций сметы не распределены ИИ — добавлены в "
            f"группу «{FALLBACK_GROUP_TITLE}»"
        )
        fallback = KtpWbsGroup(
            id=_uuid(),
            session_id=session.id,
            project_id=session.project_id,
            title=FALLBACK_GROUP_TITLE,
            sort_order=float(len(raw_groups) + 1),
            status="draft",
        )
        groups.append(fallback)
        for i_idx, est in enumerate(missing, start=1):
            items.append(
                KtpWbsItem(
                    id=_uuid(),
                    group_id=fallback.id,
                    session_id=session.id,
                    name=est.work_name,
                    sort_order=float(i_idx) * 1000.0,
                    origin="from_estimate",
                    estimate_id=est.id,
                    unit=est.unit,
                    quantity=est.quantity,
                    quantity_source="estimate",
                    review_status="accepted",
                )
            )

    return groups, items, warnings


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 1 — РУЧНЫЕ ПРАВКИ
# ─────────────────────────────────────────────────────────────────────────────

async def update_item(
    db: AsyncSession, project_id: str, item_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    item = await _get_item(db, project_id, item_id)
    if "name" in patch and patch["name"]:
        item.name = str(patch["name"]).strip()
    if "group_id" in patch and patch["group_id"]:
        target = await _get_group(db, project_id, str(patch["group_id"]))
        item.group_id = target.id
    if "review_status" in patch and patch["review_status"] in {
        "pending",
        "accepted",
        "rejected",
    }:
        item.review_status = patch["review_status"]
    if "unit" in patch:
        item.unit = (str(patch["unit"]).strip() or None) if patch["unit"] else None
    if "quantity" in patch:
        qty = patch["quantity"]
        item.quantity = float(qty) if qty not in (None, "") else None
        if item.quantity is not None:
            item.quantity_source = "user"
    if "sort_order" in patch and patch["sort_order"] is not None:
        item.sort_order = float(patch["sort_order"])
    item.updated_at = _now()
    await db.commit()
    return await get_wbs(db, project_id, item.session_id)


async def create_item(
    db: AsyncSession, project_id: str, group_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    group = await _get_group(db, project_id, group_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Имя работы не может быть пустым")
    max_order = max((float(it.sort_order) for it in group.items), default=0.0)
    item = KtpWbsItem(
        id=_uuid(),
        group_id=group.id,
        session_id=group.session_id,
        name=name,
        sort_order=max_order + 1000.0,
        origin="manual",
        review_status="accepted",
        unit=(str(payload.get("unit")).strip() or None) if payload.get("unit") else None,
        quantity=float(payload["quantity"])
        if payload.get("quantity") not in (None, "")
        else None,
        quantity_source="user" if payload.get("quantity") not in (None, "") else None,
    )
    db.add(item)
    await db.commit()
    return await get_wbs(db, project_id, group.session_id)


async def delete_item(
    db: AsyncSession, project_id: str, item_id: str
) -> dict[str, Any]:
    item = await _get_item(db, project_id, item_id)
    session_id = item.session_id
    await db.delete(item)
    await db.commit()
    return await get_wbs(db, project_id, session_id)


async def create_group(
    db: AsyncSession, project_id: str, session_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    session = await get_session_by_id(db, project_id, session_id)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("Название группы не может быть пустым")
    max_order = await db.scalar(
        select(KtpWbsGroup.sort_order)
        .where(KtpWbsGroup.session_id == session_id)
        .order_by(KtpWbsGroup.sort_order.desc())
        .limit(1)
    )
    group = KtpWbsGroup(
        id=_uuid(),
        session_id=session.id,
        project_id=project_id,
        title=title,
        sort_order=float(max_order or 0) + 1000.0,
        status="draft",
    )
    db.add(group)
    await db.commit()
    return await get_wbs(db, project_id, session_id)


async def update_group(
    db: AsyncSession, project_id: str, group_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    group = await _get_group(db, project_id, group_id)
    if "title" in patch and patch["title"]:
        group.title = str(patch["title"]).strip()
    if "sort_order" in patch and patch["sort_order"] is not None:
        group.sort_order = float(patch["sort_order"])
    if "wt_code" in patch:
        wt = patch["wt_code"]
        group.wt_code = str(wt).strip().upper() if wt else None
    group.updated_at = _now()
    await db.commit()
    return await get_wbs(db, project_id, group.session_id)


async def delete_group(
    db: AsyncSession, project_id: str, group_id: str
) -> dict[str, Any]:
    group = await _get_group(db, project_id, group_id)
    if group.items:
        raise PermissionError(
            "Нельзя удалить непустую группу — сначала перенесите или "
            "отклоните работы внутри неё"
        )
    session_id = group.session_id
    await db.delete(group)
    await db.commit()
    return await get_wbs(db, project_id, session_id)


async def approve_stage1(
    db: AsyncSession, project_id: str, session_id: str
) -> KtpEstimateSession:
    session = await get_session_by_id(db, project_id, session_id)
    pending = await db.scalar(
        select(KtpWbsItem.id)
        .where(KtpWbsItem.session_id == session_id)
        .where(KtpWbsItem.origin == "ai_added")
        .where(KtpWbsItem.review_status == "pending")
        .limit(1)
    )
    if pending:
        raise ValueError(
            "Не все добавленные ИИ работы проверены — примите или отклоните их"
        )
    session.status = "stage2_review"
    session.updated_at = _now()
    await db.commit()
    await db.refresh(session)
    return session


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 2 — КАРТОЧКИ КТП ПО ГРУППАМ
# ─────────────────────────────────────────────────────────────────────────────

def _build_stage2_prompt(
    group: KtpWbsGroup,
    items: list[KtpWbsItem],
    estimates: list[Estimate],
    clarification_answers: dict | None,
    answers: dict[str, str],
) -> str:
    lines = [f"  • {it.name}" for it in items] or ["  (нет работ)"]
    works_block = "\n".join(lines)
    estimate_rows_block = _format_estimate_rows_for_prompt(estimates)
    estimate_rows_section = (
        f"\n\nИСХОДНЫЕ СТРОКИ СМЕТЫ ДЛЯ ЭТОЙ ГРУППЫ:\n{estimate_rows_block}"
        if estimate_rows_block
        else ""
    )
    clarification_block = _format_clarification_answers_for_prompt(
        clarification_answers,
        current_group_id=group.id,
    )
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""
    answers_block = ""
    if answers:
        answers_block = "\n\nНОВЫЕ ОТВЕТЫ ПОЛЬЗОВАТЕЛЯ ПО ЭТОЙ ГРУППЕ:\n" + "\n".join(
            f"  {k}: {v}" for k, v in answers.items()
        )
    return f"""Ты эксперт-технолог в строительстве. На основе группы работ создай
КТП (Карту Технологического Процесса).

ГРУППА РАБОТ: «{group.title}»

РАБОТЫ ГРУППЫ:
{works_block}
{estimate_rows_section}
{clarification_section}
{answers_block}

ИНСТРУКЦИЯ:
1. Если данных достаточно для качественного КТП, сразу создай КТП.
2. Перед тем как задавать уточняющий вопрос, обязательно проверь:
   - данные, уже уточненные пользователем;
   - исходные строки сметы и материалы по работам этой группы.
   Если ответ уже следует из этих данных, используй его и НЕ задавай вопрос.
3. Если после проверки всё равно не хватает ключевых технических данных, верни только уточняющие вопросы.
4. Ответ верни только валидным JSON без markdown.

Если данных не хватает:
{{"sufficient": false, "questions": [
  {{"key": "concrete_grade", "label": "Какой класс бетона предусмотрен?",
   "type": "text", "hint": "Например: B25, B30"}}
]}}

Если данных достаточно:
{{"sufficient": true, "questions": [], "ktp": {{
  "title": "КТП: ...", "goal": "...",
  "steps": [{{"no": 1, "stage": "Подготовительные работы",
    "work_details": "...", "control_points": "..."}}],
  "recommendations": ["..."]
}}}}"""


async def _call_stage2(prompt: str) -> dict[str, Any]:
    raw = await create_chat_completion(
        model=settings.KTP_GENERATION_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=settings.KTP_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    return parse_json_object(raw)


async def _resolve_questions_from_known_context(
    group: KtpWbsGroup,
    items: list[KtpWbsItem],
    estimates: list[Estimate],
    clarification_answers: dict | None,
    questions: list[dict[str, Any]],
    current_answers: dict[str, str],
) -> dict[str, str]:
    if not questions:
        return {}

    clarification_block = _format_clarification_answers_for_prompt(
        clarification_answers,
        current_group_id=group.id,
    ) or "(нет)"
    estimate_rows_block = _format_estimate_rows_for_prompt(estimates) or "(нет)"
    works_block = "\n".join(f"- {it.name}" for it in items) or "(нет)"
    questions_block = "\n".join(
        f"- key={q.get('key')}: {q.get('label') or q.get('hint') or q.get('key')}"
        for q in questions
        if isinstance(q, dict)
    )
    current_answers_block = (
        "\n".join(f"- {k}: {v}" for k, v in current_answers.items())
        if current_answers
        else "(нет)"
    )

    prompt = f"""Ты проверяешь, можно ли ответить на уточняющие вопросы без пользователя.
Используй ТОЛЬКО известные данные ниже: ответы пользователя, работы WBS и исходные строки сметы.
Не додумывай проектные решения. Если ответа нет явно или надежно не следует из данных, оставь вопрос unresolved.

ГРУППА: {group.title}

УЖЕ ДАННЫЕ ОТВЕТЫ ПО ТЕКУЩЕЙ ГРУППЕ:
{current_answers_block}

НАКОПЛЕННЫЕ УТОЧНЕНИЯ:
{clarification_block}

РАБОТЫ WBS:
{works_block}

ИСХОДНЫЕ СТРОКИ СМЕТЫ:
{estimate_rows_block}

ВОПРОСЫ:
{questions_block}

Верни строго JSON:
{{"answers": {{"question_key": "ответ, найденный в известных данных"}}, "unresolved": ["question_key"]}}"""

    try:
        parsed = parse_json_object(
            await create_chat_completion(
                model=settings.KTP_GENERATION_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=min(settings.KTP_MAX_TOKENS, 2500),
                response_format={"type": "json_object"},
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("Stage2 question resolver failed for group %s", group.id)
        return {}

    allowed_keys = {
        str(q.get("key"))
        for q in questions
        if isinstance(q, dict) and q.get("key")
    }
    answers = parsed.get("answers")
    if not isinstance(answers, dict):
        return {}

    resolved: dict[str, str] = {}
    for key, value in answers.items():
        key = str(key)
        answer = str(value or "").strip()
        if key in allowed_keys and answer:
            resolved[key] = answer
    return resolved


async def generate_card_for_wbs_group(
    db: AsyncSession,
    project_id: str,
    group_id: str,
    answers: dict[str, str] | None = None,
) -> dict[str, Any]:
    group = await _get_group(db, project_id, group_id)
    items = [
        it
        for it in sorted(group.items, key=lambda x: float(x.sort_order))
        if it.review_status != "rejected"
    ]
    session = await db.get(KtpEstimateSession, group.session_id)
    batch = await db.get(EstimateBatch, session.estimate_batch_id) if session else None
    estimates = await _load_source_estimates_for_items(db, items)
    clarification_answers = batch.clarification_answers if batch else None
    prompt = _build_stage2_prompt(
        group,
        items,
        estimates,
        clarification_answers,
        answers or {},
    )

    try:
        parsed = await _call_stage2(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stage2 card generation failed for group %s", group_id)
        group.status = "card_failed"
        group.card_error_message = str(exc)
        group.updated_at = _now()
        await db.commit()
        raise

    if answers:
        group.card_answers_json = answers
        if batch:
            updated_clarification_answers = await _merge_group_answers_into_batch_with_lock(
                batch.id, group, answers
            )
            if updated_clarification_answers is not None:
                clarification_answers = updated_clarification_answers
    group.updated_at = _now()

    if not bool(parsed.get("sufficient", True)):
        questions = parsed.get("questions", [])
        if not isinstance(questions, list):
            group.status = "card_failed"
            group.card_error_message = "LLM вернул questions не списком"
            await db.commit()
            raise ValueError("LLM вернул questions не списком")

        group.card_questions_json = questions
        resolved_answers = await _resolve_questions_from_known_context(
            group=group,
            items=items,
            estimates=estimates,
            clarification_answers=clarification_answers,
            questions=questions,
            current_answers=answers or {},
        )
        if resolved_answers:
            resolved_with_user_answers = {**resolved_answers, **(answers or {})}
            if batch:
                updated_clarification_answers = await _merge_group_answers_into_batch_with_lock(
                    batch.id,
                    group,
                    resolved_answers,
                    source="known_context",
                )
                if updated_clarification_answers is not None:
                    clarification_answers = updated_clarification_answers
            retry_prompt = _build_stage2_prompt(
                group,
                items,
                estimates,
                clarification_answers,
                resolved_with_user_answers,
            )
            try:
                parsed = await _call_stage2(retry_prompt)
            except Exception:  # noqa: BLE001
                logger.exception("Stage2 retry with resolved answers failed for group %s", group_id)
            else:
                if bool(parsed.get("sufficient", True)):
                    group.card_answers_json = resolved_with_user_answers
                    ktp = parsed.get("ktp", {})
                    if not isinstance(ktp, dict):
                        group.status = "card_failed"
                        group.card_error_message = "LLM не вернул объект ktp"
                        await db.commit()
                        raise ValueError("LLM не вернул объект ktp")
                    group.card_title = ktp.get("title") or group.title
                    group.card_goal = ktp.get("goal") or ""
                    group.card_steps_json = ktp.get("steps", [])
                    group.card_recommendations_json = ktp.get("recommendations", [])
                    group.card_questions_json = None
                    group.status = "card_generated"
                    group.card_error_message = None
                    await db.commit()
                    await db.refresh(group)
                    return {
                        "sufficient": True,
                        "group_id": group.id,
                        "card": _card_payload(group),
                    }
                retry_questions = parsed.get("questions", [])
                if isinstance(retry_questions, list):
                    resolved_keys = set(resolved_answers)
                    questions = [
                        q
                        for q in retry_questions
                        if not isinstance(q, dict)
                        or str(q.get("key") or "") not in resolved_keys
                    ]

        group.card_questions_json = questions
        group.card_steps_json = None
        group.card_recommendations_json = None
        group.status = "card_questions"
        group.card_error_message = None
        await db.commit()
        return {"sufficient": False, "questions": questions}

    ktp = parsed.get("ktp", {})
    if not isinstance(ktp, dict):
        group.status = "card_failed"
        group.card_error_message = "LLM не вернул объект ktp"
        await db.commit()
        raise ValueError("LLM не вернул объект ktp")

    group.card_title = ktp.get("title") or group.title
    group.card_goal = ktp.get("goal") or ""
    group.card_steps_json = ktp.get("steps", [])
    group.card_recommendations_json = ktp.get("recommendations", [])
    group.card_questions_json = None
    group.status = "card_generated"
    group.card_error_message = None
    await db.commit()
    await db.refresh(group)
    return {
        "sufficient": True,
        "group_id": group.id,
        "card": _card_payload(group),
    }


def _card_payload(group: KtpWbsGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "title": group.card_title,
        "goal": group.card_goal,
        "steps": group.card_steps_json or [],
        "recommendations": group.card_recommendations_json or [],
        "status": group.status,
        "questions_json": group.card_questions_json,
    }


async def get_card(
    db: AsyncSession, project_id: str, group_id: str
) -> dict[str, Any]:
    group = await _get_group(db, project_id, group_id)
    return _card_payload(group)


async def update_card(
    db: AsyncSession, project_id: str, group_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    group = await _get_group(db, project_id, group_id)
    if "title" in patch:
        group.card_title = patch["title"]
    if "goal" in patch:
        group.card_goal = patch["goal"]
    if "steps" in patch and isinstance(patch["steps"], list):
        group.card_steps_json = patch["steps"]
    if "recommendations" in patch and isinstance(patch["recommendations"], list):
        group.card_recommendations_json = patch["recommendations"]
    group.updated_at = _now()
    await db.commit()
    await db.refresh(group)
    return _card_payload(group)


async def approve_stage2(
    db: AsyncSession, project_id: str, session_id: str
) -> KtpEstimateSession:
    session = await get_session_by_id(db, project_id, session_id)
    # Группа без принятых работ не идёт ни в карточку, ни в ГПР —
    # не требуем для неё card_generated, иначе approve залипнет.
    groups = list(
        await db.scalars(
            select(KtpWbsGroup)
            .where(KtpWbsGroup.session_id == session_id)
            .options(selectinload(KtpWbsGroup.items))
        )
    )
    for g in groups:
        accepted = [it for it in g.items if it.review_status != "rejected"]
        if not accepted:
            for it in g.items:
                await db.delete(it)
            await db.delete(g)
            continue
        if g.status != "card_generated":
            raise ValueError(
                "Не для всех групп с принятыми работами сгенерированы карточки КТП"
            )
    session.status = "gpr_pending"
    session.updated_at = _now()
    await db.commit()
    await db.refresh(session)
    return session
