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
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import select, text
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
    KtpSessionSubtype,
    KtpWbsGroup,
    KtpWbsGroupDependency,
    KtpWbsItem,
    WorkSubtype,
)
from app.services.ktp_service import (
    _assert_batch_belongs_to_project,
    _estimate_item_type,
)
from app.services.ktp_item_fer_service import extract_fer_unit, match_session_items, normalize_unit
from app.services.openrouter_embeddings import create_chat_completion, parse_json_object
from app.services.work_taxonomy_service import (
    UNKNOWN_SUBTYPE_CODE,
    build_work_section_palette,
    get_project_variant_stages,
    normalize_text,
)
from app.services.taxonomy_compatibility_service import (
    assert_reclassification_allowed,
    batch_uses_legacy_taxonomy,
    build_persisted_stage_catalog,
    resolved_stage_title,
)
from app.services.taxonomy_snapshot_service import resolve_config_path

logger = logging.getLogger(__name__)

PROMPT_VERSION = "estimate-v6.4"
GROUPING_MODE_STAGE_AWARE = "stage_aware"
GROUPING_MODE_ESTIMATE_STRUCTURE = "estimate_structure"

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
STAGE_AWARE_FALLBACK_TITLE = "Нераспределённые работы"
STAGE_GROUPING_AUTO_ACCEPT_MIN_SCORE = 10
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


_WORK_NAME_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize_work_name(raw: Any) -> str:
    """Каноничный ключ имени работы для дедупликации ai_added против сметы.

    Схлопывает регистр, пунктуацию и кратные пробелы. Ловит только точные/почти
    точные повторы («Гидроизоляция фундамента» ×2, дубль в двух группах). Синонимы
    («Разметка участка» vs «Услуги геодезиста») этим не отсекаются — для них в
    промпт передаётся список уже существующих работ.
    """
    text = str(raw or "").strip().casefold()
    if not text:
        return ""
    text = _WORK_NAME_PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def gpr_blocker(item: KtpWbsItem) -> bool:
    """Computed GPR blocker, not stored in DB.

    A missing personal rate is a hard duration blocker and cannot be bypassed by
    manually confirming an otherwise reviewable KTP row.
    """
    if getattr(item, "duration_block_reason", None) == "user_rate_input_required":
        return True
    return bool(
        (item.operator_review_required or item.work_type_needs_review)
        and not item.gpr_confirmed
    )


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
    session = await _get_session_raw(db, project_id, estimate_batch_id)
    if session:
        await _expire_stale_stage1_session(db, session)
    return session


async def _get_session_raw(
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
    await _expire_stale_stage1_session(db, session)
    groups = list(
        await db.scalars(
            select(KtpWbsGroup)
            .where(KtpWbsGroup.session_id == session_id)
            .options(selectinload(KtpWbsGroup.items))
            .order_by(KtpWbsGroup.sort_order, KtpWbsGroup.created_at)
        )
    )
    await _attach_stage_review_metadata(db, groups)
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

    # Этап производительности: подтипы сессии. Для мигрированных fer_* / новых
    # prod_* сессий строим таблицу лениво при первом открытии.
    subtypes: list[KtpSessionSubtype] = []
    if session.status in {"prod_pending", "prod_review"}:
        subtypes = await _load_session_subtypes(db, session_id)
        if not subtypes:
            # Ленивое построение для мигрированных fer_* сессий — фиксируем,
            # чтобы отданные фронту id существовали при последующем PATCH.
            await build_session_subtypes(db, session)
            await db.commit()
            subtypes = await _load_session_subtypes(db, session_id)

    return {
        "session": session,
        "groups": groups,
        "group_dependencies": deps,
        "session_subtypes": subtypes,
    }


async def _attach_stage_review_metadata(db: AsyncSession, groups: list[KtpWbsGroup]) -> None:
    estimate_ids = [
        item.estimate_id
        for group in groups
        for item in group.items
        if item.estimate_id
    ]
    if not estimate_ids:
        return
    estimates = {
        est.id: est
        for est in await db.scalars(select(Estimate).where(Estimate.id.in_(estimate_ids)))
    }
    for group in groups:
        for item in group.items:
            est = estimates.get(item.estimate_id)
            if not est:
                setattr(item, "_stage_needs_review", False)
                setattr(item, "_stage_review_reason", None)
                setattr(item, "_stage_confidence_percent", None)
                continue
            raw = est.raw_data if isinstance(est.raw_data, dict) else {}
            needs_review, reason, percent = _estimate_stage_review_info(est, raw)
            setattr(item, "_stage_needs_review", needs_review)
            setattr(item, "_stage_review_reason", reason)
            setattr(item, "_stage_confidence_percent", percent)
            if needs_review and not item.manual_override:
                item.operator_review_required = True


def _job_reference_time(job: Job) -> datetime | None:
    return job.started_at or job.created_at


def _is_stale_stage1_job(job: Job, now: datetime | None = None) -> bool:
    if job.type != "ktp_estimate_stage1" or job.status not in {"pending", "processing"}:
        return False
    ref_time = _job_reference_time(job)
    if ref_time is None:
        return False
    if now is None:
        now = datetime.now(ref_time.tzinfo) if ref_time.tzinfo else datetime.utcnow()
    elif ref_time.tzinfo and now.tzinfo is None:
        now = now.replace(tzinfo=ref_time.tzinfo)
    stale_after = timedelta(seconds=max(60, int(settings.KTP_STAGE1_STALE_AFTER_SECONDS)))
    return now - ref_time > stale_after


async def _expire_stale_stage1_session(
    db: AsyncSession, session: KtpEstimateSession
) -> bool:
    if session.status not in {"stage1_pending", "stage1_processing"}:
        return False
    if not session.stage1_job_id:
        return False

    job = await db.get(Job, session.stage1_job_id)
    if not job or not _is_stale_stage1_job(job):
        return False

    last_progress = (
        (job.result or {}).get("_progress") if isinstance(job.result, dict) else None
    )
    message = (
        "Обработка КТП зависла и была остановлена автоматически. "
        "Запустите построение КТП заново."
    )
    if last_progress:
        message = f"{message} Последний шаг: {last_progress}"

    job.status = "failed"
    job.result = {"error": message, "stale": True, "last_progress": last_progress}
    job.finished_at = datetime.utcnow()
    session.status = "stage1_failed"
    session.error_message = message
    await db.commit()
    return True


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
    preserve_estimate_structure: bool = False,
) -> tuple[Job | None, KtpEstimateSession]:
    """Запускает этап 1. Возвращает (job | None, session).

    job=None — сеанс уже существует (без force), новый прогон не нужен.
    """
    await _assert_batch_belongs_to_project(db, project_id, estimate_batch_id)

    existing = await _get_session_raw(db, project_id, estimate_batch_id)
    existing_was_stale = False
    if existing:
        existing_was_stale = await _expire_stale_stage1_session(db, existing)

    if existing and not force and not existing_was_stale:
        if existing.status in {"stage1_pending", "stage1_processing"}:
            existing_job = await db.get(Job, existing.stage1_job_id) if existing.stage1_job_id else None
            if existing_job and existing_job.status in {"pending", "processing"}:
                if existing_job.status == "pending":
                    try:
                        from app.tasks.estimate_import_tasks import process_ktp_estimate_stage1_job

                        process_ktp_estimate_stage1_job.delay(existing_job.id)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("failed to re-enqueue KTP estimate stage1 job %s in celery: %s", existing_job.id, exc)
                return existing_job, existing
            existing.status = "stage1_pending"
            existing.error_message = None
            existing.stage1_job_id = None
            session = existing
        else:
            return None, existing
    if existing and (force or existing_was_stale):
        await db.delete(existing)
        await db.flush()
        existing = None

    if not existing:
        session = KtpEstimateSession(
            project_id=project_id,
            estimate_batch_id=estimate_batch_id,
            status="stage1_pending",
            stage1_raw_json={
                "grouping_mode": (
                    GROUPING_MODE_ESTIMATE_STRUCTURE
                    if preserve_estimate_structure
                    else GROUPING_MODE_STAGE_AWARE
                ),
                "preserve_estimate_structure": bool(preserve_estimate_structure),
            },
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
    else:
        session.stage1_raw_json = {
            "grouping_mode": (
                GROUPING_MODE_ESTIMATE_STRUCTURE
                if preserve_estimate_structure
                else GROUPING_MODE_STAGE_AWARE
            ),
            "preserve_estimate_structure": bool(preserve_estimate_structure),
        }
        flag_modified(session, "stage1_raw_json")
        await db.flush()

    job = Job(
        id=_uuid(),
        type="ktp_estimate_stage1",
        status="pending",
        project_id=project_id,
        created_by=user_id,
        input={
            "session_id": session.id,
            "preserve_estimate_structure": bool(preserve_estimate_structure),
            "grouping_mode": (
                GROUPING_MODE_ESTIMATE_STRUCTURE
                if preserve_estimate_structure
                else GROUPING_MODE_STAGE_AWARE
            ),
        },
    )
    db.add(job)
    # Сначала INSERT Job, чтобы FK ktp_estimate_sessions.stage1_job_id
    # был валиден при последующем UPDATE сессии.
    await db.flush()
    session.stage1_job_id = job.id
    await db.commit()
    await db.refresh(session)

    try:
        from app.tasks.estimate_import_tasks import process_ktp_estimate_stage1_job

        process_ktp_estimate_stage1_job.delay(job.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to enqueue KTP estimate stage1 job %s in celery: %s", job.id, exc)
        job.status = "failed"
        job.result = {"error": "Не удалось поставить построение КТП в очередь"}
        job.finished_at = datetime.utcnow()
        session.status = "stage1_failed"
        session.error_message = job.result["error"]
        await db.commit()
    return job, session


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 1 — ФОНОВАЯ ОБРАБОТКА
# ─────────────────────────────────────────────────────────────────────────────

async def _process_stage1(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        if job.status not in {"pending", "processing"}:
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
            preserve_estimate_structure = bool(job.input.get("preserve_estimate_structure"))
            grouping_mode = (
                GROUPING_MODE_ESTIMATE_STRUCTURE
                if preserve_estimate_structure
                else GROUPING_MODE_STAGE_AWARE
            )
            batch = await db.get(EstimateBatch, session.estimate_batch_id)
            if not batch:
                raise ValueError("Блок сметы не найден")
            estimates = await _load_work_estimates(
                db, session.project_id, session.estimate_batch_id
            )
            if not estimates:
                raise ValueError("В блоке сметы нет строк работ для построения КТП")

            await _progress(
                f"Загружено {len(estimates)} позиций сметы, "
                + (
                    "строим структуру по разделам сметы…"
                    if preserve_estimate_structure
                    else "строим структуру по этапам JSON v6…"
                )
            )

            # row_key -> estimate
            row_keys: dict[str, Estimate] = {
                f"R{idx:03d}": est for idx, est in enumerate(estimates, start=1)
            }

            work_section_palette = await build_work_section_palette(db, estimates)
            kind_label = ESTIMATE_KIND_LABELS.get(
                batch.estimate_kind, "Строительные работы"
            )

            diagnostics: dict[str, Any] = {}
            raw_groups = await _run_stage1_ai(
                estimates,
                row_keys,
                work_section_palette,
                kind_label,
                batch.clarification_answers,
                _progress,
                diagnostics,
                batch=batch,
                preserve_estimate_structure=preserve_estimate_structure,
            )

            await _progress("Сохраняем структуру работ…")
            groups, items, coverage_warnings = _materialize_wbs(
                session, raw_groups, row_keys, owner_user_id=job.created_by
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
            invalid_section_codes = diagnostics.get("invalid_work_section_codes") or []
            if invalid_section_codes:
                warnings_out.append(
                    f"ИИ вернул {len(invalid_section_codes)} неизвестных кодов секций JSON v6; "
                    "для этих групп секция оставлена пустой"
                )
            stage_grouping = diagnostics.get("stage_grouping") or {}
            fallback_rows = (stage_grouping.get("fallback_rows") or []) + (
                stage_grouping.get("invalid_stage_rows") or []
            )
            if fallback_rows:
                warnings_out.append(
                    f"{len(fallback_rows)} позиций не попали в канонический этап JSON v6 — "
                    f"добавлены в «{STAGE_AWARE_FALLBACK_TITLE}»"
                )
            review_rows = stage_grouping.get("review_rows") or []
            if review_rows:
                warnings_out.append(
                    f"{len(review_rows)} позиций имеют stage/subtype needs_review — проверьте их на шаге структуры"
                )

            session.stage1_raw_json = {
                "grouping_mode": grouping_mode,
                "preserve_estimate_structure": preserve_estimate_structure,
                "estimate_type_id": batch.estimate_type_id,
                "project_variant_id": batch.project_variant_id,
                "groups": raw_groups,
                "stage_grouping": diagnostics.get("stage_grouping") or {},
                "chunk_errors": chunk_errors,
                "raw_samples": diagnostics.get("raw_samples") or [],
                "coverage": diagnostics.get("coverage") or [],
                "wt_code_conflicts": diagnostics.get("wt_code_conflicts") or [],
                "work_section_code_conflicts": diagnostics.get("work_section_code_conflicts") or [],
                "invalid_work_section_codes": diagnostics.get("invalid_work_section_codes") or [],
                "gap_fill_trimmed": diagnostics.get("gap_fill_trimmed") or [],
                "repeated_sections": diagnostics.get("repeated_sections") or [],
                "unassigned_ai_items": diagnostics.get("unassigned_ai_items") or [],
                "gap_fill_duplicates": diagnostics.get("gap_fill_duplicates") or [],
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
    work_section_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
    diagnostics: dict[str, Any] | None = None,
    *,
    batch: EstimateBatch | None = None,
    preserve_estimate_structure: bool = False,
) -> list[dict[str, Any]]:
    """Возвращает канонический список групп {title, work_section_code, items:[…]}.

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
    diagnostics.setdefault("work_section_code_conflicts", [])
    diagnostics.setdefault("invalid_work_section_codes", [])
    diagnostics.setdefault("gap_fill_trimmed", [])
    diagnostics.setdefault("repeated_sections", [])
    diagnostics.setdefault("unassigned_ai_items", [])
    diagnostics.setdefault("gap_fill_duplicates", [])

    estimate_to_row_key = {est.id: row_key for row_key, est in row_keys.items()}

    if not preserve_estimate_structure:
        if batch is None:
            raise ValueError("Блок сметы не передан для stage-aware группировки")
        if on_progress:
            await on_progress("Группируем работы по каноническим этапам JSON v6…")
        return _build_stage_aware_groups(estimates, estimate_to_row_key, batch, diagnostics)

    python_groups = _build_python_groups(estimates, estimate_to_row_key, diagnostics)
    ungrouped_rows = python_groups.pop("__ungrouped__", None)

    has_real_sections = bool(python_groups)
    has_ungrouped = bool(ungrouped_rows and ungrouped_rows["rows"])

    if not has_real_sections:
        diagnostics["chunk_errors"].append(
            {"chunk": "no_sections", "error": "В смете не заполнены разделы — используем legacy-промпт"}
        )
        return await _run_stage1_legacy(
            row_keys, work_section_palette, kind_label, clarification_answers, on_progress, diagnostics
        )

    if has_ungrouped:
        if on_progress:
            await on_progress(
                f"Распределяем {len(ungrouped_rows['rows'])} позиций без раздела…"
            )
        await _run_ungrouped_pass(
            ungrouped_rows["rows"],
            python_groups,
            work_section_palette,
            kind_label,
            clarification_answers,
            diagnostics,
        )

    await _run_section_clean_pass(
        python_groups,
        work_section_palette,
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


def _stage_section_key(stage_number: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(stage_number)).strip("_").lower()
    return f"stage_{normalized or hashlib.sha1(str(stage_number).encode('utf-8')).hexdigest()[:8]}"


def _stage_title(stage_number: str | None, stage_title: str | None) -> str:
    number = str(stage_number or "").strip()
    title = str(stage_title or "").strip()
    if number and title:
        return f"{number}. {title}"
    return title or number or FALLBACK_DISPLAY_TITLE


def _estimate_stage_number(est: Estimate) -> str | None:
    raw = est.raw_data if isinstance(est.raw_data, dict) else {}
    value = est.work_stage_number or raw.get("work_stage_number")
    value = str(value).strip() if value is not None else ""
    return value or None


def _estimate_stage_title(est: Estimate) -> str | None:
    return resolved_stage_title(est)


_WEAK_STAGE_TEXT_MATCH_TYPES = {
    "stage_option_match",
    "near_stage_title_match",
    "canonical_title_match",
}


def _terms_have_explicit_phrase(terms: list[str] | None) -> bool:
    return any(len(normalize_text(term).split()) > 1 for term in terms or [])


def _stage_score_weak_partial_reason(stage_score: dict[str, Any]) -> str | None:
    candidates = stage_score.get("candidate_scores")
    top = candidates[0] if isinstance(candidates, list) and candidates else None
    if not isinstance(top, dict):
        return None
    if str(top.get("match_type") or "") not in _WEAK_STAGE_TEXT_MATCH_TYPES:
        return None
    matched = top.get("matched_terms") if isinstance(top.get("matched_terms"), dict) else {}
    if (
        matched.get("primary_work_type")
        or matched.get("related_work_types")
        or matched.get("occurrence_label")
        or matched.get("stage_title_exact")
    ):
        return None
    if _terms_have_explicit_phrase(matched.get("stage_option")):
        return None
    if _terms_have_explicit_phrase(matched.get("stage_title")):
        return None
    if _terms_have_explicit_phrase(matched.get("canonical_stage")):
        return None
    signal_terms = (
        len(matched.get("stage_option") or [])
        + len(matched.get("stage_title") or [])
        + len(matched.get("canonical_stage") or [])
    )
    if signal_terms:
        return "stage_weak_partial_text_match"
    return None


def _stage_score_high_confidence_partial(stage_score: dict[str, Any]) -> bool:
    winner = stage_score.get("winner") if isinstance(stage_score.get("winner"), dict) else {}
    try:
        winner_score = int(winner.get("score") or 0)
    except (TypeError, ValueError):
        winner_score = 0
    candidates = stage_score.get("candidate_scores")
    top = candidates[0] if isinstance(candidates, list) and candidates else None
    if not isinstance(top, dict):
        return False
    matched = top.get("matched_terms") if isinstance(top.get("matched_terms"), dict) else {}
    unique_terms = {
        normalize_text(term)
        for key in ("stage_option", "stage_title", "canonical_stage")
        for term in (matched.get(key) or [])
        if normalize_text(term)
    }
    return winner_score >= 14 and len(unique_terms) >= 2


def _stage_score_has_primary_winner(stage_score: dict[str, Any]) -> bool:
    winner = stage_score.get("winner") if isinstance(stage_score.get("winner"), dict) else {}
    try:
        winner_score = int(winner.get("score") or 0)
    except (TypeError, ValueError):
        winner_score = 0
    candidates = stage_score.get("candidate_scores")
    top = candidates[0] if isinstance(candidates, list) and candidates else None
    if not isinstance(top, dict):
        return False
    matched = top.get("matched_terms") if isinstance(top.get("matched_terms"), dict) else {}
    return winner_score >= STAGE_GROUPING_AUTO_ACCEPT_MIN_SCORE and bool(matched.get("primary_work_type"))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _stage_confidence_percent(stage_score: dict[str, Any] | None) -> int | None:
    if not isinstance(stage_score, dict):
        return None
    winner = stage_score.get("winner") if isinstance(stage_score.get("winner"), dict) else {}
    try:
        score = float(winner.get("score"))
        delta = float(stage_score.get("delta_top_1_top_2"))
    except (TypeError, ValueError):
        return None
    score_part = _clamp(score / 14.0, 0.0, 1.0)
    delta_part = _clamp(delta / 3.0, 0.0, 1.0)
    return round(100 * min(score_part, delta_part))


def _estimate_stage_review_info(est: Estimate, raw: dict[str, Any]) -> tuple[bool, str | None, int | None]:
    if bool(getattr(est, "manual_override", False) or raw.get("manual_override")):
        return False, None, None
    stage_score = getattr(est, "stage_match_score_json", None)
    if not isinstance(stage_score, dict):
        stage_score = raw.get("stage_match_score_json") if isinstance(raw.get("stage_match_score_json"), dict) else None
    percent = _stage_confidence_percent(stage_score)
    if isinstance(stage_score, dict):
        weak_reason = _stage_score_weak_partial_reason(stage_score)
        if weak_reason:
            return True, weak_reason, percent
        reason = str(stage_score.get("reason") or "").strip()
        if bool(stage_score.get("needs_review")):
            return True, reason or "stage_needs_review", percent
        return False, None, percent
    if est.needs_review or raw.get("needs_review"):
        return True, est.review_reason or raw.get("review_reason") or "stage_needs_review", percent
    return False, None, percent


def _estimate_stage_review_reason(est: Estimate, raw: dict[str, Any]) -> str | None:
    needs_review, reason, _percent = _estimate_stage_review_info(est, raw)
    return reason if needs_review else None


def _estimate_work_type_review_reason(est: Estimate, raw: dict[str, Any]) -> str | None:
    if bool(getattr(est, "manual_override", False) or raw.get("manual_override")):
        return None
    subtype_code = (
        getattr(est, "work_subtype_code", None)
        or raw.get("work_subtype_code")
        or raw.get("subtype_code")
    )
    section_id = getattr(est, "section_id", None) or raw.get("section_id") or getattr(est, "work_section_code", None)
    subtype_id = getattr(est, "subtype_id", None)
    if not subtype_id and isinstance(subtype_code, str) and "/" in subtype_code:
        section_from_code, subtype_id = subtype_code.split("/", 1)
        section_id = section_id or section_from_code
    unresolved_code = not subtype_code or subtype_code == UNKNOWN_SUBTYPE_CODE
    unresolved_pair = not section_id or not subtype_id
    if unresolved_code or unresolved_pair:
        return "work_type_unresolved"
    return None


def _build_stage_aware_groups(
    estimates: list[Estimate],
    estimate_to_row_key: dict[str, str],
    batch: EstimateBatch,
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build WBS groups from JSON v6 work_stage instead of estimate sections."""
    if isinstance(batch.taxonomy_snapshot, dict):
        estimate_type_snapshot = batch.taxonomy_snapshot.get("estimate_type") or {}
        variant_snapshot = batch.taxonomy_snapshot.get("variant") or {}
        if not batch.estimate_type_id and estimate_type_snapshot.get("id"):
            batch.estimate_type_id = str(estimate_type_snapshot["id"])
        if not batch.estimate_type_title and estimate_type_snapshot.get("title"):
            batch.estimate_type_title = str(estimate_type_snapshot["title"])
        if not batch.estimate_type_number and estimate_type_snapshot.get("number"):
            batch.estimate_type_number = str(estimate_type_snapshot["number"])
        if not batch.project_variant_id:
            snapshot_variant_id = batch.taxonomy_snapshot.get("project_variant_id") or variant_snapshot.get("id")
            if snapshot_variant_id:
                batch.project_variant_id = str(snapshot_variant_id)
        if not batch.project_variant_title and variant_snapshot.get("title"):
            batch.project_variant_title = str(variant_snapshot["title"])
        if not batch.project_variant_number and variant_snapshot.get("number"):
            batch.project_variant_number = str(variant_snapshot["number"])

    if not batch.estimate_type_id or not batch.project_variant_id:
        raise ValueError(
            "Некорректная Stage 10 смета: отсутствует зафиксированный тип сметы или вариант объекта."
        )
    legacy_taxonomy = batch_uses_legacy_taxonomy(batch, estimates)
    if legacy_taxonomy:
        allowed_stages = build_persisted_stage_catalog(estimates)
        if not allowed_stages:
            raise ValueError(
                "В старой смете не сохранены названия этапов. "
                "Автоматически разрешать её через новый справочник запрещено."
            )
    elif isinstance(batch.building_params, dict) and batch.building_params.get("floors_count"):
        try:
            from app.services.work_taxonomy_service import get_project_variant_stage_instances

            allowed_stages = get_project_variant_stage_instances(
                str(batch.estimate_type_id),
                str(batch.project_variant_id),
                batch.building_params,
            )
        except ValueError as exc:
            raise ValueError(
                "Выбранный тип сметы/вариант объекта не найден в справочнике JSON v6"
            ) from exc
    elif isinstance(batch.taxonomy_snapshot, dict) and isinstance(
        (batch.taxonomy_snapshot.get("variant") or {}).get("stages"),
        list,
    ):
        allowed_stages = copy.deepcopy(batch.taxonomy_snapshot["variant"]["stages"])
    else:
        try:
            allowed_stages = get_project_variant_stages(
                str(batch.estimate_type_id),
                str(batch.project_variant_id),
            )
        except ValueError as exc:
            raise ValueError(
                "Выбранный тип сметы/вариант объекта не найден в справочнике JSON v6"
            ) from exc

    stage_by_number = {
        str(stage.get("number") or ""): stage
        for stage in allowed_stages
        if stage.get("number")
    }
    stage_order = {
        str(stage.get("number") or ""): (index + 1) * 1000.0
        for index, stage in enumerate(allowed_stages)
        if stage.get("number")
    }
    stage_grouping = diagnostics.setdefault(
        "stage_grouping",
        {
            "mode": GROUPING_MODE_STAGE_AWARE,
            "estimate_type_id": batch.estimate_type_id,
            "project_variant_id": batch.project_variant_id,
            "taxonomy_source": (
                "persisted_snapshot"
                if legacy_taxonomy or isinstance(batch.taxonomy_snapshot, dict)
                else "runtime_dictionary"
            ),
            "legacy_taxonomy": legacy_taxonomy,
            "fallback_rows": [],
            "invalid_stage_rows": [],
            "review_rows": [],
        },
    )
    groups: dict[str, dict[str, Any]] = {}
    fallback_items: list[dict[str, Any]] = []

    for stage in allowed_stages:
        stage_number = str(stage.get("number") or "").strip()
        if not stage_number:
            continue
        section_key = _stage_section_key(stage_number)
        groups[section_key] = {
            "title": _stage_title(stage_number, stage.get("title")),
            "sort_order": stage_order.get(stage_number, float(10**8)),
            "wt_code": None,
            "work_section_code": None,
            "work_section_name": None,
            "section_key": section_key,
            "work_stage_number": stage_number,
            "work_stage_title": stage.get("title"),
            "canonical_stage_id": stage.get("canonical_stage_id"),
            "stage_options_mode": stage.get("stage_options_mode") or "none",
            "items": [],
        }

    for est in sorted(estimates, key=lambda e: (e.row_order or 0, e.id)):
        row_key = estimate_to_row_key.get(est.id)
        if not row_key:
            continue
        raw = est.raw_data if isinstance(est.raw_data, dict) else {}
        stage_number = _estimate_stage_number(est)
        stage = stage_by_number.get(stage_number or "")
        if not stage_number:
            fallback_items.append(
                {"name": est.work_name, "origin": "from_estimate", "row_key": row_key}
            )
            stage_grouping["fallback_rows"].append(
                {"row_key": row_key, "estimate_id": est.id, "reason": "missing_work_stage_number"}
            )
            continue
        if not stage:
            fallback_items.append(
                {"name": est.work_name, "origin": "from_estimate", "row_key": row_key}
            )
            stage_grouping["invalid_stage_rows"].append(
                {
                    "row_key": row_key,
                    "estimate_id": est.id,
                    "work_stage_number": stage_number,
                }
            )
            continue

        stage_review_reason = _estimate_stage_review_reason(est, raw)
        if stage_review_reason:
            stage_grouping["review_rows"].append(
                {
                    "row_key": row_key,
                    "estimate_id": est.id,
                    "work_stage_number": stage_number,
                    "review_reason": stage_review_reason,
                }
            )

        work_type_review_reason = _estimate_work_type_review_reason(est, raw)
        if work_type_review_reason:
            stage_grouping["review_rows"].append(
                {
                    "row_key": row_key,
                    "estimate_id": est.id,
                    "work_stage_number": stage_number,
                    "review_reason": est.review_reason or raw.get("review_reason"),
                    "work_type_review_reason": work_type_review_reason,
                }
            )

        section_key = _stage_section_key(stage_number)
        bucket = groups[section_key]
        bucket["items"].append(
            {"name": est.work_name, "origin": "from_estimate", "row_key": row_key}
        )

    result = sorted(groups.values(), key=lambda item: (float(item["sort_order"]), item["section_key"]))
    if fallback_items:
        result.append(
            {
                "title": STAGE_AWARE_FALLBACK_TITLE,
                "sort_order": float(10**9),
                "wt_code": None,
                "work_section_code": None,
                "work_section_name": None,
                "section_key": FALLBACK_SECTION_KEY,
                "items": fallback_items,
            }
        )
        diagnostics["coverage"].append(
            {
                "kind": "stage_aware_fallback",
                "missing": [item["row_key"] for item in fallback_items],
                "unknown": [],
            }
        )
    return result


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
    section_code = parsed.get("work_section_code")
    if section_code is None:
        section_code = parsed.get("wt_code")  # legacy LLM/test compatibility
    section_code = (
        str(section_code).strip()
        if isinstance(section_code, str) and section_code.strip()
        else None
    )
    items: list[dict[str, Any]] = []
    for raw_it in items_raw:
        if not isinstance(raw_it, dict):
            continue
        row_key = raw_it.get("row_key")
        if not isinstance(row_key, str) or not row_key.strip():
            continue
        name = str(raw_it.get("name") or "").strip()
        items.append({"row_key": row_key.strip(), "name": name})
    return {"cleaned_title": cleaned_title, "work_section_code": section_code, "items": items}


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


def _format_work_section_palette_for_prompt(
    work_section_palette: list[dict[str, Any]],
) -> str:
    primary: list[str] = []
    secondary: list[str] = []
    for section in work_section_palette:
        code = str(section.get("section_code") or "").strip()
        name = str(section.get("section_name") or "").strip()
        if not code or not name:
            continue
        examples = [
            str(example.get("work_subtype_name") or "").strip()
            for example in (section.get("examples") or [])
            if isinstance(example, dict) and str(example.get("work_subtype_name") or "").strip()
        ]
        suffix = f" | примеры: {'; '.join(examples)}" if examples else ""
        line = f"- {code}: {name}{suffix}"
        if section.get("is_primary"):
            primary.append(line)
        else:
            secondary.append(line)
    parts: list[str] = []
    if primary:
        parts.append("Основные секции по классификации строк сметы:\n" + "\n".join(primary))
    if secondary:
        parts.append("Остальные секции справочника для добавленных работ:\n" + "\n".join(secondary))
    return "\n\n".join(parts)


def _section_name_by_code(work_section_palette: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(section.get("section_code")): str(section.get("section_name") or "")
        for section in work_section_palette
        if section.get("section_code") and section.get("section_name")
    }


def _build_section_prompt(
    *,
    kind_label: str,
    display_title: str,
    rows: list[tuple[str, Estimate]],
    work_section_palette: list[dict[str, Any]],
    clarification_answers: dict | None,
) -> str:
    palette_block = _format_work_section_palette_for_prompt(work_section_palette) or "(палитра пуста)"
    rows_block = _format_rows_for_prompt(rows)
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    return f"""Тип объекта: {kind_label}
Группа работ (из сметы): «{display_title}»

ПАЛИТРА СЕКЦИЙ JSON v6 (выбери ОДИН work_section_code для этой группы):
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
3. Подбери ОДИН work_section_code из палитры, наиболее подходящий всей группе.
4. Для КАЖДОГО row_key из списка верни запись с этим row_key и нормализованным
   "name" (убрать сокращения и опечатки). НЕ объединяй похожие позиции,
   НЕ удаляй ничего — исходные строки сметы должны вернуться все.

Верни строго JSON без markdown:
{{
  "cleaned_title": "Кровля",
  "work_section_code": "roofing",
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
    project_works: list[str],
    clarification_answers: dict | None,
) -> str:
    items_block = "\n".join(f"- {it['name']}" for it in items) or "(пусто)"
    project_block = "\n".join(f"- {w}" for w in project_works) or "(нет)"
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    return f"""Тип объекта: {kind_label}
Группа работ: «{display_title}»

РАБОТЫ В ЭТОЙ ГРУППЕ:
{items_block}

УЖЕ ЕСТЬ В ПРОЕКТЕ (во всех группах — НЕ предлагай повторно):
{project_block}
{clarification_section}

ЗАДАЧА:
1. Определи, каких работ ВНУТРИ ИМЕННО ЭТОЙ ГРУППЫ технологически не хватает,
   чтобы её можно было выполнить.
2. НЕ предлагай работу, которая уже есть в проекте (список выше) — включая её
   синонимы, переформулировки и под-операции. Если сомневаешься — не добавляй.
3. Добавляй ТОЛЬКО физические строительно-монтажные работы (устройство, монтаж,
   демонтаж, укладка, кладка). НЕ добавляй проверки, измерения, изыскания,
   контроль качества, обследования, разметку, согласования — это не отдельные
   работы ГПР.
4. Верни не более {PER_GROUP_GAP_FILL_MAX_ITEMS} пунктов. Пустой список — норма.
5. Каждая запись обязательно содержит "ai_reason" с короткой причиной.
6. Не добавляй работы из других групп.

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

ГРУППЫ И ИХ РАБОТЫ (group_key, название, уже включённые работы):
{groups_block}
{clarification_section}

ЗАДАЧА:
1. Опираясь на состав проекта и ответы пользователя, предложи технологически
   обязательные работы, которых в проекте НЕТ вообще (демонтаж, пусконаладка,
   вывоз мусора, благоустройство и т.п.).
2. НЕ предлагай работу, которая уже есть в любой группе (сверяйся со списком
   works у каждой группы) — включая её синонимы, переформулировки и под-операции.
   Если сомневаешься — не добавляй.
3. Добавляй ТОЛЬКО физические строительно-монтажные работы (устройство, монтаж,
   демонтаж, укладка, кладка). НЕ добавляй проверки, измерения, изыскания,
   контроль качества, обследования, разметку, согласования — это не отдельные
   работы ГПР.
4. Постарайся распределить такие работы в ИМЕЮЩИЕСЯ группы по group_key.
5. Если работа не подходит ни к одной группе — помести её в "unassigned".
6. Не более {PROJECT_GAP_FILL_MAX_DISTRIBUTED} записей в distributed
   и не более {PROJECT_GAP_FILL_MAX_UNASSIGNED} в unassigned.
7. У каждой записи обязательно "ai_reason".

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
    work_section_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None = None,
    gap_fill: bool = False,
) -> str:
    rows_block = _format_rows_for_prompt(rows)
    palette_block = _format_work_section_palette_for_prompt(work_section_palette) or "(палитра пуста)"
    clarification_block = _format_clarification_answers_for_prompt(clarification_answers)
    clarification_section = f"\n\n{clarification_block}" if clarification_block else ""

    gap_instruction = (
        "7. Добавь технологически необходимые работы, которые ОТСУТСТВУЮТ в "
        "смете, но обязательны для этого типа объекта (подготовительные, "
        "демонтаж, пусконаладка, вывоз мусора, благоустройство). НЕ дублируй "
        "работы, уже присутствующие в списке (в т.ч. синонимы и под-операции), "
        "и добавляй ТОЛЬКО физические строительно-монтажные работы — без "
        "проверок, измерений, изысканий, контроля и разметки. Помечай их "
        '"origin": "ai_added" и заполняй "ai_reason".'
        if gap_fill
        else "7. НЕ добавляй работы, которых нет в списке позиций — только "
        "группируй и нормализуй переданные позиции."
    )

    return f"""Тип объекта: {kind_label}

СПРАВОЧНО (категории работ JSON v6 — используй work_section_code из палитры):
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
  {{"title": "Земляные работы", "sort_order": 1, "work_section_code": "earthworks",
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
    work_section_palette: list[dict[str, Any]],
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
    work_section_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    on_progress: Callable[[str], Awaitable[None]] | None,
    diagnostics: dict[str, Any],
) -> None:
    """C: per-section clean-only LLM-вызов. Заполняет cleaned_items и work_section_code."""
    chunk_size = max(20, int(settings.KTP_ESTIMATE_CHUNK_ROWS))
    sections_ordered = sorted(python_groups.values(), key=lambda g: g["sort_order"])
    total = len(sections_ordered)
    valid_sections = _section_name_by_code(work_section_palette)

    for idx, grp in enumerate(sections_ordered, start=1):
        rows = grp["rows"]
        if not rows:
            grp["cleaned_items"] = []
            grp["work_section_code"] = None
            grp["work_section_name"] = None
            grp["cleaned_title"] = grp["display_title"]
            continue

        if on_progress:
            await on_progress(
                f"ИИ чистит группу «{grp['display_title']}» ({idx}/{total}, {len(rows)} позиций)…"
            )

        chunks = [rows[i : i + chunk_size] for i in range(0, len(rows), chunk_size)]
        all_items: list[dict[str, Any]] = []
        section_code_votes: list[str] = []
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
                work_section_palette=work_section_palette,
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
            if validated["work_section_code"]:
                section_code = validated["work_section_code"]
                if section_code in valid_sections:
                    section_code_votes.append(section_code)
                else:
                    diagnostics["invalid_work_section_codes"].append(
                        {
                            "section_key": grp["section_key"],
                            "chunk": chunk_label,
                            "invalid_code": section_code,
                        }
                    )
            if cleaned_title is None and validated["cleaned_title"]:
                cleaned_title = validated["cleaned_title"]

        # majority vote
        final_section_code: str | None = None
        if section_code_votes:
            counter = Counter(section_code_votes)
            final_section_code = counter.most_common(1)[0][0]
            if len(set(section_code_votes)) > 1:
                diagnostics["work_section_code_conflicts"].append(
                    {
                        "section_key": grp["section_key"],
                        "votes": dict(counter),
                        "chosen": final_section_code,
                    }
                )

        grp["cleaned_items"] = all_items
        grp["work_section_code"] = final_section_code
        grp["work_section_name"] = valid_sections.get(final_section_code) if final_section_code else None
        grp["cleaned_title"] = cleaned_title or grp["display_title"]


async def _run_per_group_gap_fill(
    python_groups: dict[str, dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    diagnostics: dict[str, Any],
) -> None:
    """E.1: внутри каждой группы добавляем недостающие работы (max 3)."""
    # Плоский список всех работ проекта — чтобы ИИ не предлагал то, что уже есть
    # в других группах (кросс-групповые дубли вида «Армирование фундамента»).
    project_works = [
        it["name"]
        for grp in python_groups.values()
        for it in (grp.get("cleaned_items") or [])
        if it.get("name")
    ]
    for grp in python_groups.values():
        items = grp.get("cleaned_items") or []
        if not items:
            continue
        prompt = _build_per_group_gap_fill_prompt(
            kind_label=kind_label,
            display_title=grp.get("cleaned_title") or grp["display_title"],
            items=items,
            project_works=project_works,
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
        {
            "group_key": grp["section_key"],
            "title": grp.get("cleaned_title") or grp["display_title"],
            "works": [
                it["name"]
                for it in (grp.get("cleaned_items") or []) + (grp.get("gap_items") or [])
                if it.get("name")
            ],
        }
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

    # Дедуп ai_added gap-items: против имён работ из сметы/структуры и между
    # собой. Снимает повторы вида «Армирование фундамента» в двух группах и
    # «Гидроизоляция фундамента», уже присутствующую в смете.
    existing_names: set[str] = set()
    for est in row_keys.values():
        norm = _normalize_work_name(est.work_name)
        if norm:
            existing_names.add(norm)
    for grp in python_groups.values():
        for it in grp.get("cleaned_items") or []:
            norm = _normalize_work_name(it.get("name"))
            if norm:
                existing_names.add(norm)
    seen_gap_names: set[str] = set()
    dropped_dups = diagnostics.setdefault("gap_fill_duplicates", [])

    for grp in sorted(python_groups.values(), key=lambda g: g["sort_order"]):
        items: list[dict[str, Any]] = []
        for it in grp.get("cleaned_items") or []:
            row_key = it.get("row_key")
            if isinstance(row_key, str):
                if row_key in seen_row_keys:
                    continue
                seen_row_keys.add(row_key)
            items.append(it)
        for it in grp.get("gap_items") or []:
            norm = _normalize_work_name(it.get("name"))
            if not norm:
                continue
            if norm in existing_names or norm in seen_gap_names:
                dropped_dups.append(
                    {
                        "name": it.get("name"),
                        "section_key": grp["section_key"],
                        "reason": (
                            "exists_in_estimate"
                            if norm in existing_names
                            else "duplicate_gap"
                        ),
                    }
                )
                continue
            seen_gap_names.add(norm)
            items.append(it)
        result.append(
            {
                "title": grp.get("cleaned_title") or grp["display_title"] or FALLBACK_DISPLAY_TITLE,
                "sort_order": float(grp["sort_order"]),
                "wt_code": None,
                "work_section_code": grp.get("work_section_code"),
                "work_section_name": grp.get("work_section_name"),
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
                "work_section_code": None,
                "work_section_name": None,
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
    work_section_palette: list[dict[str, Any]],
    kind_label: str,
    clarification_answers: dict | None,
    on_progress: Callable[[str], Awaitable[None]] | None,
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Старое поведение: LLM группирует по технологической последовательности."""
    chunk_size = max(20, int(settings.KTP_ESTIMATE_CHUNK_ROWS))
    keys = list(row_keys.keys())
    valid_sections = _section_name_by_code(work_section_palette)

    def _clean_group_section(group: dict[str, Any], label: str) -> None:
        raw_code = group.get("work_section_code") or group.get("wt_code")
        code = str(raw_code).strip() if isinstance(raw_code, str) and raw_code.strip() else None
        if code and code in valid_sections:
            group["work_section_code"] = code
            group["work_section_name"] = valid_sections[code]
        else:
            if code:
                diagnostics["invalid_work_section_codes"].append(
                    {"chunk": label, "invalid_code": code}
                )
            group["work_section_code"] = None
            group["work_section_name"] = None
        group["wt_code"] = None

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
            work_section_palette,
            kind_label,
            clarification_answers,
            gap_fill=True,
        )
        groups, err = await _call_and_parse_legacy(prompt, "legacy/single")
        if err and not groups:
            return []
        for group in groups:
            _clean_group_section(group, "legacy/single")
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
            work_section_palette,
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
                    "wt_code": None,
                    "work_section_code": grp.get("work_section_code"),
                    "work_section_name": None,
                    "items": [],
                }
                merged[slug] = bucket
            if bucket.get("work_section_code") is None:
                bucket["work_section_code"] = grp.get("work_section_code")
                bucket["work_section_name"] = grp.get("work_section_name")
            bucket["items"].extend(grp.get("items") or [])

    groups = list(merged.values())
    for group in groups:
        _clean_group_section(group, "legacy/merged")
    return groups


def _materialize_wbs(
    session: KtpEstimateSession,
    raw_groups: list[dict[str, Any]],
    row_keys: dict[str, Estimate],
    *,
    owner_user_id: str | None = None,
) -> tuple[list[KtpWbsGroup], list[KtpWbsItem], list[str]]:
    """Create WBS objects and expand one Estimate into stage-instance KTP items.

    Dynamic-floor projections are grouped by ``stage_instance_id``.  This is
    essential for GPR: walls/slab of floor 1 and floor 2 must be distinct groups
    even though they originate from the same stage template and financial row.
    """
    from app.services.ktp_floor_sequence_service import (
        catalog_labor_for_projection,
        projection_group_descriptor,
        projection_metadata,
    )

    groups: list[KtpWbsGroup] = []
    items: list[KtpWbsItem] = []
    warnings: list[str] = []
    seen_estimate_ids: set[str] = set()
    groups_by_key: dict[str, KtpWbsGroup] = {}
    session_owner_user_id = (
        owner_user_id
        or getattr(session, "owner_user_id", None)
        or getattr(session, "created_by", None)
        or getattr(session, "user_id", None)
    )

    def _set_metadata(target: Any, values: dict[str, Any]) -> None:
        # The delivery archive does not contain real ORM models.  Setting the
        # attributes after construction keeps backward compatibility; once the
        # stage-10 ORM migration is applied these fields are persisted.
        for key, value in values.items():
            try:
                setattr(target, key, value)
            except Exception:  # noqa: BLE001 - optional compatibility metadata
                logger.debug("Cannot set KTP metadata %s on %r", key, target)

    def _ensure_group(
        raw_group: dict[str, Any],
        group_index: int,
        projection: dict[str, Any] | None,
    ) -> KtpWbsGroup:
        descriptor = projection_group_descriptor(
            raw_group, projection, fallback_index=group_index
        )
        existing = groups_by_key.get(descriptor.key)
        if existing is not None:
            return existing

        wt_code = raw_group.get("wt_code")
        wt_code = (
            str(wt_code).strip().upper()
            if isinstance(wt_code, str) and str(wt_code).strip()
            else None
        )
        raw_section_code = raw_group.get("work_section_code")
        work_section_code = (
            str(raw_section_code).strip()
            if isinstance(raw_section_code, str) and str(raw_section_code).strip()
            else None
        )
        raw_section_name = raw_group.get("work_section_name")
        work_section_name = (
            str(raw_section_name).strip()
            if isinstance(raw_section_name, str) and str(raw_section_name).strip()
            else None
        )
        group = KtpWbsGroup(
            id=_uuid(),
            session_id=session.id,
            project_id=session.project_id,
            title=descriptor.title,
            sort_order=descriptor.sort_order,
            wt_code=wt_code,
            work_section_code=work_section_code,
            work_section_name=work_section_name,
            status="draft",
        )
        _set_metadata(
            group,
            {
                "stage_instance_id": descriptor.stage_instance_id,
                "template_stage_number": descriptor.template_stage_number,
                "stage_number": descriptor.stage_number,
                "canonical_stage_id": descriptor.canonical_stage_id,
                "floor_number": descriptor.floor_number,
                "floor_kind": descriptor.floor_kind,
                "floor_label": descriptor.floor_label,
                "floor_component": descriptor.floor_component,
                "component_role": descriptor.component_role,
            },
        )
        groups_by_key[descriptor.key] = group
        groups.append(group)
        return group

    def _work_type_fields(name: str, estimate: Estimate | None) -> dict[str, Any]:
        raw = estimate.raw_data if estimate and isinstance(estimate.raw_data, dict) else {}
        if estimate is not None:
            stage_needs_review, _stage_reason, _stage_percent = _estimate_stage_review_info(estimate, raw)
            work_type_needs_review = bool(
                estimate.classification_needs_review
                or raw.get("classification_needs_review")
            )
            return {
                "work_section_code": estimate.work_section_code or raw.get("work_section_code"),
                "work_section_name": estimate.work_section_name or raw.get("work_section_name"),
                "work_subtype_code": estimate.work_subtype_code or raw.get("work_subtype_code") or raw.get("subtype_code"),
                "work_subtype_name": estimate.work_subtype_name or raw.get("work_subtype_name") or raw.get("subtype_name"),
                "work_type_confidence": raw.get("work_type_confidence") or estimate.classification_confidence or raw.get("classification_confidence"),
                "work_type_needs_review": work_type_needs_review,
                "work_type_candidates": estimate.classification_candidates or raw.get("classification_candidates"),
                "work_type_source": estimate.classification_source or raw.get("classification_source"),
                "operator_review_required": bool(
                    stage_needs_review
                    or estimate.operator_review_required
                    or raw.get("operator_review_required")
                    or work_type_needs_review
                ),
                "manual_override": bool(estimate.manual_override or raw.get("manual_override")),
            }
        from app.services.work_taxonomy_service import (
            UNKNOWN_SUBTYPE_CODE,
            UNKNOWN_SUBTYPE_NAME,
            classify_work,
        )

        try:
            result = classify_work(name, None)
        except Exception as exc:  # noqa: BLE001
            logger.exception("KTP item work type classification failed: %s", name)
            return {
                "work_section_code": None,
                "work_section_name": None,
                "work_subtype_code": UNKNOWN_SUBTYPE_CODE,
                "work_subtype_name": UNKNOWN_SUBTYPE_NAME,
                "work_type_confidence": "low",
                "work_type_needs_review": True,
                "work_type_candidates": [],
                "work_type_source": "rule_based_error",
                "operator_review_required": True,
                "manual_override": False,
            }
        return {
            "work_section_code": result.section_code,
            "work_section_name": result.section_name,
            "work_subtype_code": result.subtype_code,
            "work_subtype_name": result.subtype_name,
            "work_type_confidence": result.confidence,
            "work_type_needs_review": bool(result.needs_review),
            "work_type_candidates": [c.as_dict() for c in result.candidates],
            "work_type_source": result.source,
            "operator_review_required": bool(result.needs_review),
            "manual_override": False,
        }

    def _append_item(
        *,
        raw_group: dict[str, Any],
        group_index: int,
        item_index: int,
        projection_index: int,
        projection: dict[str, Any],
        raw_item: dict[str, Any],
        estimate: Estimate | None,
        origin: str,
        fallback_name: str,
    ) -> None:
        group = _ensure_group(raw_group, group_index, projection)
        projected_name = str(projection.get("name") or fallback_name).strip() or fallback_name
        work_type_fields = _work_type_fields(projected_name, estimate)
        labor = (
            catalog_labor_for_projection(
                estimate, projection, owner_user_id=session_owner_user_id
            )
            if estimate else {}
        )
        if projection.get("needs_review") or labor.get("needs_review"):
            work_type_fields["operator_review_required"] = True

        item = KtpWbsItem(
            id=_uuid(),
            group_id=group.id,
            session_id=session.id,
            name=projected_name,
            sort_order=float(item_index) * 1000.0 + projection_index / 1000.0,
            origin=origin,
            estimate_id=estimate.id if estimate else None,
            unit=projection.get("unit") if estimate else None,
            quantity=projection.get("quantity") if estimate else None,
            quantity_source=(projection.get("quantity_source") if estimate else None),
            review_status=(
                "pending"
                if origin == "ai_added"
                or projection.get("needs_review")
                or labor.get("needs_review")
                else "accepted"
            ),
            ai_reason=(
                str(raw_item.get("ai_reason")).strip()
                if raw_item.get("ai_reason")
                else projection.get("review_reason") or labor.get("review_reason")
            ),
            **work_type_fields,
        )
        _set_metadata(item, projection_metadata(projection))
        if labor:
            _set_metadata(
                item,
                {
                    "labor_hours": labor.get("labor_hours"),
                    "norm_source": labor.get("norm_source"),
                    "norm_kind": labor.get("norm_kind"),
                    "norm_value": labor.get("norm_value"),
                    "norm_unit": labor.get("norm_unit"),
                    "norm_ref": labor.get("norm_ref"),
                    "duration_block_reason": (
                        labor.get("review_reason")
                        if labor.get("review_reason") == "user_rate_input_required"
                        else None
                    ),
                },
            )
        items.append(item)

    for g_idx, raw_g in enumerate(raw_groups, start=1):
        raw_items = raw_g.get("items") or []
        ai_item_counter = 0
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
                origin = "ai_added"

            if estimate is not None:
                if estimate.id in seen_estimate_ids:
                    warnings.append(
                        f"Позиция «{estimate.work_name}» продублирована ИИ — оставлена одна копия"
                    )
                    continue
                seen_estimate_ids.add(estimate.id)
                from app.services.quantity_projection_service import (
                    ktp_projection_payloads_for_estimate,
                )
                projection_payloads = ktp_projection_payloads_for_estimate(estimate)
            else:
                ai_item_counter += 1
                projection_payloads = [{
                    "name": name,
                    "quantity": None,
                    "unit": None,
                    "quantity_source": None,
                    "needs_review": False,
                }]

            for projection_index, projection in enumerate(projection_payloads, start=1):
                _append_item(
                    raw_group=raw_g,
                    group_index=g_idx,
                    item_index=i_idx if estimate else ai_item_counter,
                    projection_index=projection_index,
                    projection=projection,
                    raw_item=raw_it,
                    estimate=estimate,
                    origin=origin,
                    fallback_name=name,
                )

    # Coverage invariant: every Estimate row is consumed once.  It may produce
    # zero calculable KTP items only when package resolution explicitly
    # suppressed all its projections.
    missing = [est for est in row_keys.values() if est.id not in seen_estimate_ids]
    if missing:
        warnings.append(
            f"{len(missing)} позиций сметы не распределены ИИ — добавлены в группу «{FALLBACK_GROUP_TITLE}»"
        )
        fallback_raw = {
            "title": FALLBACK_GROUP_TITLE,
            "sort_order": float(len(raw_groups) + 1),
            "section_key": FALLBACK_SECTION_KEY,
        }
        from app.services.quantity_projection_service import (
            ktp_projection_payloads_for_estimate,
        )
        for i_idx, est in enumerate(missing, start=1):
            for projection_index, projection in enumerate(
                ktp_projection_payloads_for_estimate(est), start=1
            ):
                _append_item(
                    raw_group=fallback_raw,
                    group_index=len(raw_groups) + 1,
                    item_index=i_idx,
                    projection_index=projection_index,
                    projection=projection,
                    raw_item={},
                    estimate=est,
                    origin="from_estimate",
                    fallback_name=est.work_name,
                )

    groups.sort(key=lambda group: (float(group.sort_order or 0), str(group.title or ""), str(group.id)))
    return groups, items, warnings


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 1 — РУЧНЫЕ ПРАВКИ
# ─────────────────────────────────────────────────────────────────────────────

async def _apply_manual_work_subtype(
    db: AsyncSession,
    item: KtpWbsItem,
    code: str,
) -> None:
    ref = await db.scalar(select(WorkSubtype).where(WorkSubtype.code == code))
    if not ref:
        raise ValueError(f"Подтип работ {code} не найден")

    previous_code = item.work_subtype_code
    item.work_section_code = ref.section_code
    item.work_section_name = ref.section_name
    item.work_subtype_code = ref.code
    item.work_subtype_name = ref.name
    item.work_type_confidence = "manual"
    item.work_type_needs_review = False
    item.work_type_candidates = []
    item.work_type_source = "manual"
    item.operator_review_required = False
    item.manual_override = True
    item.gpr_confirmed = False

    if item.estimate_id:
        estimate = await db.get(Estimate, item.estimate_id)
        if estimate:
            estimate.work_section_code = ref.section_code
            estimate.work_section_name = ref.section_name
            estimate.work_subtype_code = ref.code
            estimate.work_subtype_name = ref.name
            estimate.classification_confidence = "manual"
            estimate.classification_needs_review = False
            estimate.classification_source = "manual"
            estimate.classification_candidates = []
            estimate.operator_review_required = False
            estimate.operator_review_status = (
                "confirmed" if previous_code == ref.code else "changed"
            )
            estimate.operator_review_reason = None
            estimate.manual_override = True
            estimate.manual_changed_at = _now()
            raw = estimate.raw_data if isinstance(estimate.raw_data, dict) else {}
            raw.update(
                {
                    "work_section_code": ref.section_code,
                    "work_section_name": ref.section_name,
                    "work_subtype_code": ref.code,
                    "work_subtype_name": ref.name,
                    "subtype_code": ref.code,
                    "subtype_name": ref.name,
                    "classification_confidence": "manual",
                    "classification_needs_review": False,
                    "classification_source": "manual",
                    "classification_candidates": [],
                    "operator_review_required": False,
                    "operator_review_status": estimate.operator_review_status,
                    "operator_review_reason": None,
                    "manual_override": True,
                }
            )
            estimate.raw_data = raw
            flag_modified(estimate, "raw_data")


async def _reset_item_work_type(
    db: AsyncSession,
    item: KtpWbsItem,
    *,
    force_taxonomy_migration: bool = False,
) -> None:
    from app.services.work_taxonomy_service import classify_work

    estimate = await db.get(Estimate, item.estimate_id) if item.estimate_id else None
    if estimate is not None:
        assert_reclassification_allowed(
            estimate,
            force_migrate=force_taxonomy_migration,
        )
    name = (estimate.work_name if estimate else item.name) or item.name
    section = estimate.section if estimate else None
    result = classify_work(name or "", section)

    item.work_section_code = result.section_code
    item.work_section_name = result.section_name
    item.work_subtype_code = result.subtype_code
    item.work_subtype_name = result.subtype_name
    item.work_type_confidence = result.confidence
    item.work_type_needs_review = bool(result.needs_review)
    item.work_type_candidates = [c.as_dict() for c in result.candidates]
    item.work_type_source = result.source
    item.operator_review_required = bool(result.needs_review)
    item.manual_override = False
    item.gpr_confirmed = False

    if estimate:
        estimate.work_section_code = result.section_code
        estimate.work_section_name = result.section_name
        estimate.work_subtype_code = result.subtype_code
        estimate.work_subtype_name = result.subtype_name
        estimate.classification_score = result.score
        estimate.classification_confidence = result.confidence
        estimate.classification_needs_review = bool(result.needs_review)
        estimate.classification_source = result.source
        estimate.classification_candidates = [c.as_dict() for c in result.candidates]
        estimate.classification_matched_terms = result.matched_terms
        estimate.operator_review_required = bool(result.needs_review)
        estimate.operator_review_status = None
        estimate.operator_review_reason = result.reason if result.needs_review else None
        estimate.dictionary_version = result.dictionary_version
        estimate.manual_override = False
        estimate.manual_changed_at = None
        raw = estimate.raw_data if isinstance(estimate.raw_data, dict) else {}
        raw.update(result.as_raw_data())
        raw["operator_review_required"] = bool(result.needs_review)
        raw["operator_review_status"] = None
        raw["operator_review_reason"] = result.reason if result.needs_review else None
        raw["manual_override"] = False
        estimate.raw_data = raw
        flag_modified(estimate, "raw_data")


async def _confirm_item_review(
    db: AsyncSession,
    item: KtpWbsItem,
) -> None:
    item.operator_review_required = False
    item.work_type_needs_review = False
    item.work_type_confidence = item.work_type_confidence or "manual"
    item.manual_override = True
    item.gpr_confirmed = False

    if item.estimate_id:
        estimate = await db.get(Estimate, item.estimate_id)
        if estimate:
            estimate.needs_review = False
            estimate.review_reason = None
            estimate.classification_needs_review = False
            estimate.operator_review_required = False
            estimate.operator_review_status = "confirmed"
            estimate.operator_review_reason = None
            estimate.stage_match_type = "manual_operator_override"
            estimate.stage_confidence = "high"
            estimate.manual_override = True
            estimate.manual_changed_at = _now()
            raw = estimate.raw_data if isinstance(estimate.raw_data, dict) else {}
            raw.update(
                {
                    "needs_review": False,
                    "review_reason": None,
                    "classification_needs_review": False,
                    "operator_review_required": False,
                    "operator_review_status": "confirmed",
                    "operator_review_reason": None,
                    "stage_match_type": "manual_operator_override",
                    "stage_confidence": "high",
                    "manual_override": True,
                    "stage_match_score_json": {
                        "manual_override": True,
                        "source": "manual_operator_override",
                        "previous": raw.get("stage_match_score_json"),
                    },
                }
            )
            estimate.raw_data = raw
            flag_modified(estimate, "raw_data")


async def _rebuild_subtypes_if_needed(
    db: AsyncSession,
    session_id: str,
) -> None:
    session = await db.get(KtpEstimateSession, session_id)
    if session and session.status in {"prod_pending", "prod_review"}:
        await build_session_subtypes(db, session)


async def update_item(
    db: AsyncSession, project_id: str, item_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    item = await _get_item(db, project_id, item_id)
    work_type_changed = False
    if "name" in patch and patch["name"]:
        item.name = str(patch["name"]).strip()
    if "group_id" in patch and patch["group_id"]:
        target = await _get_group(db, project_id, str(patch["group_id"]))
        item.group_id = target.id
        if item.operator_review_required or item.work_type_needs_review:
            await _confirm_item_review(db, item)
            work_type_changed = True
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
    if patch.get("manual_override") is False and patch.get("reclassify"):
        await _reset_item_work_type(
            db,
            item,
            force_taxonomy_migration=bool(patch.get("force_taxonomy_migration")),
        )
        work_type_changed = True
    elif "work_subtype_code" in patch and patch["work_subtype_code"]:
        await _apply_manual_work_subtype(db, item, str(patch["work_subtype_code"]))
        work_type_changed = True
    elif patch.get("manual_override") is True:
        await _confirm_item_review(db, item)
        work_type_changed = True
    if work_type_changed:
        await _rebuild_subtypes_if_needed(db, item.session_id)
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
    from app.services.work_taxonomy_service import (
        UNKNOWN_SUBTYPE_CODE,
        UNKNOWN_SUBTYPE_NAME,
        classify_work,
    )

    try:
        result = classify_work(name, None)
        work_type_fields = {
            "work_section_code": result.section_code,
            "work_section_name": result.section_name,
            "work_subtype_code": result.subtype_code,
            "work_subtype_name": result.subtype_name,
            "work_type_confidence": result.confidence,
            "work_type_needs_review": bool(result.needs_review),
            "work_type_candidates": [c.as_dict() for c in result.candidates],
            "work_type_source": result.source,
            "operator_review_required": bool(result.needs_review),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Manual KTP item work type classification failed: %s", name)
        work_type_fields = {
            "work_section_code": None,
            "work_section_name": None,
            "work_subtype_code": UNKNOWN_SUBTYPE_CODE,
            "work_subtype_name": UNKNOWN_SUBTYPE_NAME,
            "work_type_confidence": "low",
            "work_type_needs_review": True,
            "work_type_candidates": [],
            "work_type_source": "rule_based_error",
            "operator_review_required": True,
        }
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
        **work_type_fields,
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
    review_pending = await db.scalar(
        select(KtpWbsItem.id)
        .where(KtpWbsItem.session_id == session_id)
        .where(KtpWbsItem.review_status != "rejected")
        .where(KtpWbsItem.manual_override.is_(False))
        .where(KtpWbsItem.work_type_needs_review.is_(True))
        .limit(1)
    )
    if review_pending:
        raise ValueError(
            "Есть строки структуры, требующие проверки — подтвердите их или исправьте тип работ"
        )
    estimate_review_rows = await db.execute(
        select(KtpWbsItem, Estimate)
        .join(Estimate, KtpWbsItem.estimate_id == Estimate.id)
        .where(KtpWbsItem.session_id == session_id)
        .where(KtpWbsItem.review_status != "rejected")
        .where(KtpWbsItem.manual_override.is_(False))
    )
    for item, estimate in estimate_review_rows:
        raw = estimate.raw_data if isinstance(estimate.raw_data, dict) else {}
        stage_needs_review, _stage_reason, _stage_percent = _estimate_stage_review_info(estimate, raw)
        work_type_needs_review = bool(
            estimate.classification_needs_review
            or raw.get("classification_needs_review")
        )
        if stage_needs_review or work_type_needs_review:
            item.operator_review_required = True
            raise ValueError(
                "Есть строки структуры, требующие проверки — подтвердите их или исправьте тип работ"
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
    extra_directive: str = "",
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
    directive_block = f"\n\n{extra_directive.strip()}" if extra_directive.strip() else ""
    return f"""Ты эксперт-технолог в строительстве. На основе группы работ создай
КТП (Карту Технологического Процесса).

ГРУППА РАБОТ: «{group.title}»

РАБОТЫ ГРУППЫ:
{works_block}
{estimate_rows_section}
{clarification_section}
{answers_block}{directive_block}

ИНСТРУКЦИЯ:
1. Если данных достаточно для качественного КТП, сразу создай КТП.
2. Перед тем как задавать уточняющий вопрос, обязательно проверь:
   - данные, уже уточненные пользователем;
   - исходные строки сметы и материалы по работам этой группы.
   Если ответ уже следует из этих данных, используй его и НЕ задавай вопрос.
3. НЕ задавай вопросы про марку/класс/тип бетона, а также про марки и
   характеристики материалов — они не влияют на состав и технологическую
   последовательность работ КТП. При необходимости прими типовое решение сам.
4. Если после проверки всё равно не хватает ключевых ТЕХНОЛОГИЧЕСКИХ данных
   (влияющих на состав или порядок работ), верни только уточняющие вопросы.
5. Ответ верни только валидным JSON без markdown.

Если данных не хватает:
{{"sufficient": false, "questions": [
  {{"key": "<код_вопроса>", "label": "<краткий вопрос по технологии работ>",
   "type": "text", "hint": "<пример ответа>"}}
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


# Вопросы про марку/класс/тип бетона относятся к материалам, а не к технологии,
# и на состав работ КТП не влияют — такие окна пользователю не показываем.
_IGNORED_QUESTION_RE = re.compile(
    r"(марк\w*|класс\w*|тип\w*)\s+бетон|бетон\w*\s+(марк|класс)|concrete[_\s-]?grade",
    re.IGNORECASE,
)

IGNORED_QUESTION_DIRECTIVE = (
    "ВАЖНО: не задавай вопрос про марку/класс/тип бетона — прими типовое "
    "решение и сразу составь КТП (sufficient: true)."
)


def _is_ignored_question(q: Any) -> bool:
    if not isinstance(q, dict):
        return False
    key = str(q.get("key") or "")
    if "concrete_grade" in key.lower():
        return True
    blob = f"{key} {q.get('label') or ''} {q.get('hint') or ''}"
    return bool(_IGNORED_QUESTION_RE.search(blob))


def _filter_card_questions(questions: list[Any]) -> list[Any]:
    """Отсеивает несущественные для КТП уточнения (марка/класс бетона)."""
    return [q for q in questions if not _is_ignored_question(q)]


async def _persist_generated_card(
    db: AsyncSession, group: KtpWbsGroup, ktp: Any
) -> dict[str, Any]:
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
    return {"sufficient": True, "group_id": group.id, "card": _card_payload(group)}


async def _generate_card_ignoring_questions(
    db: AsyncSession,
    group: KtpWbsGroup,
    items: list[KtpWbsItem],
    estimates: list[Estimate],
    clarification_answers: dict | None,
    answers: dict[str, str] | None,
) -> dict[str, Any] | None:
    """Все вопросы оказались несущественными — генерируем КТП с типовым решением
    вместо показа пустого окна вопросов. None — если LLM всё равно не дал карту."""
    prompt = _build_stage2_prompt(
        group,
        items,
        estimates,
        clarification_answers,
        answers or {},
        extra_directive=IGNORED_QUESTION_DIRECTIVE,
    )
    try:
        parsed = await _call_stage2(prompt)
    except Exception:  # noqa: BLE001
        logger.exception("Stage2 forced card (ignored questions) failed for group %s", group.id)
        return None
    if not bool(parsed.get("sufficient", True)):
        return None
    return await _persist_generated_card(db, group, parsed.get("ktp", {}))


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

        questions = _filter_card_questions(questions)
        if not questions:
            # LLM спросил только про несущественное (марка бетона) — генерируем
            # карточку с типовым решением, не показывая пустое окно вопросов.
            forced = await _generate_card_ignoring_questions(
                db, group, items, estimates, clarification_answers, answers
            )
            if forced is not None:
                return forced

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
                    questions = _filter_card_questions(
                        [
                            q
                            for q in retry_questions
                            if not isinstance(q, dict)
                            or str(q.get("key") or "") not in resolved_keys
                        ]
                    )

        if not questions:
            forced = await _generate_card_ignoring_questions(
                db, group, items, estimates, clarification_answers, answers
            )
            if forced is not None:
                return forced

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
    # Сразу строим таблицу производительности по подтипам и переходим на этап 4.
    await build_session_subtypes(db, session)
    session.status = "prod_review"
    session.updated_at = _now()
    await db.commit()
    await db.refresh(session)
    return session


async def skip_stage2(
    db: AsyncSession, project_id: str, session_id: str
) -> KtpEstimateSession:
    session = await get_session_by_id(db, project_id, session_id)
    if session.status != "stage2_review":
        raise ValueError("Пропустить КТП можно только на этапе КТП")

    groups = list(
        await db.scalars(
            select(KtpWbsGroup)
            .where(KtpWbsGroup.session_id == session_id)
            .options(selectinload(KtpWbsGroup.items))
        )
    )
    accepted_count = 0
    for group in groups:
        accepted = [item for item in group.items if item.review_status != "rejected"]
        if not accepted:
            for item in group.items:
                await db.delete(item)
            await db.delete(group)
            continue
        accepted_count += len(accepted)

    if accepted_count <= 0:
        raise ValueError("В структуре нет принятых работ для расчёта производительности")

    await build_session_subtypes(db, session)
    session.status = "prod_review"
    session.updated_at = _now()
    await db.commit()
    await db.refresh(session)
    return session


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 4 — ПРОИЗВОДИТЕЛЬНОСТЬ ПО ПОДТИПАМ РАБОТ
# ─────────────────────────────────────────────────────────────────────────────

UNKNOWN_SUBTYPE_NAME = "Требует ручной классификации"
_DEFAULT_VOLUME = 100.0


SESSION_SUBTYPE_ITEM_SEP = "::"


def session_subtype_code(item: KtpWbsItem, code: str) -> str:
    """Код строки производительности: каждая работа — отдельная строка «как есть».

    Раньше работы схлопывались по (код подтипа, ед.изм.), из-за чего разные работы
    одного грубого подтипа (напр. вся кладка → «Стены несущие») сливались, а их
    имена терялись. Теперь ключ уникален по ``item.id``; чистый код подтипа
    сохраняется префиксом (``base_subtype_code``) для дефолтов и отображения.
    Должно совпадать в ``build_session_subtypes`` и в подборе норм ГПР.
    """
    return f"{code}{SESSION_SUBTYPE_ITEM_SEP}{item.id}"


def base_subtype_code(stored_code: str) -> str:
    """Чистый код подтипа из хранимого per-item кода (для справочника/отображения)."""
    return stored_code.split(SESSION_SUBTYPE_ITEM_SEP, 1)[0]


def _resolve_item_subtype(
    item: KtpWbsItem,
    estimate: Estimate | None,
    taxonomy: list,
    subtypes_by_code: dict[str, WorkSubtype],
) -> tuple[str, str, str | None, str | None]:
    """Определить (subtype_code, subtype_name, macro_name, unit) для работы КТП.

    Порядок: item.work_subtype_code → Estimate.work_subtype_code → raw_data
    сметы → классификация по имени → ``unknown/needs_review``.
    """
    from app.services.work_taxonomy_service import classify_work

    code: str | None = None
    name: str | None = None
    unit = item.unit or (estimate.unit if estimate else None)

    if item.work_subtype_code:
        code = item.work_subtype_code
        name = item.work_subtype_name

    if not code and estimate and estimate.work_subtype_code:
        code = estimate.work_subtype_code
        name = estimate.work_subtype_name

    raw = estimate.raw_data if estimate and isinstance(estimate.raw_data, dict) else {}
    if not code and (raw.get("work_subtype_code") or raw.get("subtype_code")):
        code = str(raw.get("work_subtype_code") or raw["subtype_code"])
        name = raw.get("work_subtype_name") or raw.get("subtype_name") or None

    if not code:
        result = classify_work(item.name or "", estimate.section if estimate else None)
        code = result.subtype_code
        name = result.subtype_name
        if result.subtype_code != UNKNOWN_SUBTYPE_CODE:
            item.work_section_code = result.section_code
            item.work_section_name = result.section_name
            item.work_subtype_code = result.subtype_code
            item.work_subtype_name = result.subtype_name
            item.work_type_confidence = result.confidence
            item.work_type_needs_review = bool(result.needs_review)
            item.work_type_candidates = [c.as_dict() for c in result.candidates]
            item.work_type_source = result.source
            item.operator_review_required = bool(result.needs_review)

    if not code or code == UNKNOWN_SUBTYPE_CODE:
        return UNKNOWN_SUBTYPE_CODE, UNKNOWN_SUBTYPE_NAME, None, unit

    ref = subtypes_by_code.get(code)
    name = (ref.name if ref else None) or name or code
    macro_name = ref.macro_name if ref else None
    return code, name, macro_name, unit


async def _load_session_subtypes(
    db: AsyncSession, session_id: str
) -> list[KtpSessionSubtype]:
    rows = list(
        await db.scalars(
            select(KtpSessionSubtype)
            .where(KtpSessionSubtype.session_id == session_id)
            .order_by(KtpSessionSubtype.subtype_code, KtpSessionSubtype.unit)
        )
    )
    await _attach_session_subtype_rate_projection(db, session_id, rows)
    return rows


def _rate_projection_attrs() -> tuple[str, ...]:
    return (
        "selected_rate_item_id",
        "selected_rate_mapping_id",
        "rate_unit_code",
        "item_unit_code",
        "unit_conversion_factor",
        "labor_hours_per_unit_min",
        "labor_hours_per_unit_avg",
        "labor_hours_per_unit_max",
        "effective_labor_hours_per_unit_min",
        "effective_labor_hours_per_unit_avg",
        "effective_labor_hours_per_unit_max",
        "session_calculated_labor_hours_min",
        "session_calculated_labor_hours_avg",
        "session_calculated_labor_hours_max",
        "rate_auto_applicable",
        "rate_needs_review",
        "rate_review_reason",
        "resolved_labor_source",
        "resolved_labor_hours",
        "rate_catalog_version",
        "rate_catalog_file",
        "rate_trace",
    )


def _clear_rate_projection(row: KtpSessionSubtype, reason: str | None) -> None:
    for attr in _rate_projection_attrs():
        setattr(row, attr, None)
    row.rate_auto_applicable = False
    row.rate_needs_review = True
    row.rate_review_reason = reason
    row.rate_trace = {"selection_result": reason} if reason else None


def _row_optional_attr(row: Any, name: str) -> Any:
    return getattr(row, name, None)


def _set_row_projection_attr(row: Any, name: str, value: Any) -> None:
    try:
        setattr(row, name, value)
    except AttributeError:
        return


def _stored_operator_rate_selection(row: Any) -> dict[str, Any]:
    for payload in (
        getattr(row, "rate_unit_conversion", None),
        getattr(row, "rate_trace", None),
    ):
        if not isinstance(payload, dict):
            continue
        selection = payload.get("operator_selection")
        if isinstance(selection, dict):
            return dict(selection)
    selected_rate_item_id = _row_optional_attr(row, "selected_rate_item_id")
    selected_rate_mapping_id = _row_optional_attr(row, "selected_rate_mapping_id")
    if selected_rate_item_id or selected_rate_mapping_id:
        return {
            "selected_rate_item_id": selected_rate_item_id,
            "selected_rate_mapping_id": selected_rate_mapping_id,
            "output_per_day": _row_optional_attr(row, "output_per_day"),
        }
    return {}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _per_item_labor(
    labor_hours_per_norm: float | None,
    *,
    norm_base_quantity: float | None,
    unit_conversion_factor: float | None,
) -> float | None:
    labor = _float_or_none(labor_hours_per_norm)
    base = _float_or_none(norm_base_quantity) or 1.0
    factor = _float_or_none(unit_conversion_factor)
    if labor is None or factor is None:
        return None
    return round(labor * factor / base, 6)


def _rate_candidate_trace(
    *,
    candidate: dict[str, Any],
    rate_item: Any,
    rate_mapping_id: str | None,
    source: Any,
    normalized_value: float | None,
) -> dict[str, Any]:
    payload = rate_item.source_payload if rate_item is not None and isinstance(rate_item.source_payload, dict) else {}
    source_labor = payload.get("source_labor") if isinstance(payload.get("source_labor"), dict) else {}
    measurement = payload.get("measurement") if isinstance(payload.get("measurement"), dict) else {}
    source_value = source_labor.get("value")
    source_unit = source_labor.get("unit")
    shift_hours = source_labor.get("shift_duration_hours")
    measurement_raw = measurement.get("raw") or getattr(rate_item, "unit_raw", None)
    unit_code = getattr(rate_item, "unit_code", None)
    if source_unit and unit_code:
        source_unit = f"{source_unit}/{unit_code}"
    elif source_unit and measurement_raw:
        source_unit = f"{source_unit}/{measurement_raw}"
    normalized_unit = None
    if rate_item is not None and getattr(rate_item, "unit_code", None):
        normalized_unit = f"person_hour/{rate_item.unit_code}"
    approval_status = (
        getattr(rate_item, "resolution_status", None)
        or getattr(rate_item, "review_status", None)
        or candidate.get("approval_status")
    )
    return {
        "rate_item_id": getattr(rate_item, "id", None) or candidate.get("rate_item_id"),
        "rate_mapping_id": rate_mapping_id or candidate.get("rate_mapping_id"),
        "name": candidate.get("name") or getattr(rate_item, "name", None),
        "unit_code": getattr(rate_item, "unit_code", None) or candidate.get("unit_code"),
        "source_file": getattr(source, "source_file", None),
        "source_kind": getattr(source, "source_kind", None),
        "source_rate_id": getattr(rate_item, "source_rate_id", None) or candidate.get("source_rate_id"),
        "source_value": source_value,
        "source_unit": source_unit,
        "shift_duration_hours": shift_hours,
        "normalized_value": normalized_value,
        "normalized_unit": normalized_unit,
        "norm_base_quantity": getattr(rate_item, "norm_base_quantity", None) or candidate.get("norm_base_quantity"),
        "conversion_factor": candidate.get("conversion_factor"),
        "rate_context_code": candidate.get("rate_context_code"),
        "approval_status": approval_status,
        "rate_value_mode": getattr(rate_item, "rate_value_mode", None),
        "labor_basis": getattr(rate_item, "labor_basis", None),
        "auto_applicable": bool(getattr(rate_item, "auto_applicable", False)) if rate_item is not None else False,
        "approved_as_rate": bool(getattr(rate_item, "approved_as_rate", False)) if rate_item is not None else False,
        "selected_target_code": payload.get("selected_target_code"),
        "all_target_codes": payload.get("all_target_codes") or [],
        "target_kind": payload.get("target_kind"),
        "diagnostics": {
            "metadata_provisional": approval_status == "requires_manual_approval",
            "source_provisional": payload.get("norm_status") in {"provisional_typical", "provisional"},
            "requires_verification": bool(payload.get("requires_verification")),
        },
    }


def _confirmed_rate_unit_conversion(
    payload: Any,
    *,
    source_unit: str | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("conversion_status") != "user_confirmed":
        return None
    target_unit = str(payload.get("target_unit") or "").strip() or None
    input_unit = str(payload.get("input_unit") or payload.get("source_unit") or "").strip() or None
    factor = _float_or_none(payload.get("conversion_factor"))
    if not target_unit or not input_unit or factor is None:
        return None
    if source_unit and input_unit != source_unit:
        return None
    result = dict(payload)
    result["input_unit"] = input_unit
    result["source_unit"] = input_unit
    result["target_unit"] = target_unit
    result["conversion_factor"] = factor
    return result


def _suggest_rate_unit_conversion(
    *,
    text: str | None,
    source_quantity: float | None,
    source_unit: str | None,
    target_unit: str | None,
    operation_code: str | None,
) -> dict[str, Any] | None:
    if not text or not source_quantity or source_quantity <= 0 or not source_unit or not target_unit:
        return None
    normalized = text.lower().replace("ё", "е")
    if source_unit == "m2" and target_unit == "m3" and operation_code in {"block_masonry", "brick_masonry"}:
        match = re.search(r"\b(\d{2,3}(?:[,.]\d+)?)\s*мм\b", normalized)
        if not match:
            return {
                "conversion_status": "requires_user_input",
                "conversion_method": "area_to_volume_by_thickness",
                "input_quantity": source_quantity,
                "source_quantity": source_quantity,
                "input_unit": source_unit,
                "source_unit": source_unit,
                "target_unit": target_unit,
                "parameters": {},
                "formula_version": "1",
            }
        thickness_m = float(match.group(1).replace(",", ".")) / 1000.0
        factor = thickness_m
        derived_quantity = source_quantity * factor
        return {
            "conversion_status": "requires_confirmation",
            "conversion_method": "area_to_volume_by_thickness",
            "input_quantity": source_quantity,
            "source_quantity": source_quantity,
            "input_unit": source_unit,
            "source_unit": source_unit,
            "target_unit": target_unit,
            "parameters": {"thickness_m": round(thickness_m, 6)},
            "formula_version": "1",
            "conversion_factor": round(factor, 6),
            "derived_quantity": round(derived_quantity, 6),
        }
    return None


def _package_component_rate_candidates(
    *,
    selector: Any,
    package_code: str | None,
    taxonomy_code: str,
    object_scope_code: str | None,
    quantity: float | None,
    unit_code: str | None,
    work_name: str | None,
    item_text: str | None,
    spec: str | None,
    section_title: str | None,
    section_description: str | None,
    section_parent_context: str | None,
    catalog: Any,
    applicability: dict[str, Any],
    unit_conversion_overrides: dict[tuple[str, str], float] | None,
) -> list[dict[str, Any]]:
    if not package_code:
        return []
    package = getattr(selector, "operation_packages", {}).get(package_code)
    if not isinstance(package, dict):
        return []
    components = [str(code) for code in package.get("included_operations") or [] if code]
    if not components:
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str]] = set()
    for component_code in components:
        component_selection = selector.select_rate(
            taxonomy_code=taxonomy_code,
            operation_code=component_code,
            object_scope_code=object_scope_code,
            quantity=quantity,
            unit_code=unit_code,
            work_name=work_name,
            item_text=item_text,
            spec=spec,
            section_title=section_title,
            section_description=section_description,
            section_parent_context=section_parent_context,
            items=catalog.items,
            mappings=catalog.mappings,
            sources=catalog.sources,
            applicability=applicability,
            unit_conversion_overrides=unit_conversion_overrides,
        )
        component_rows = list(component_selection.candidates or [])
        if component_selection.rate_item_id and not any(
            isinstance(row, dict) and row.get("rate_item_id") == component_selection.rate_item_id
            for row in component_rows
        ):
            component_rows.insert(
                0,
                {
                    "rate_item_id": component_selection.rate_item_id,
                    "rate_mapping_id": component_selection.rate_mapping_id,
                    "source_rate_id": component_selection.source_rate_id,
                    "name": None,
                    "unit_code": component_selection.unit_code,
                    "norm_base_quantity": component_selection.norm_base_quantity,
                    "rate_context_code": component_selection.rate_context_code,
                    "labor_avg": component_selection.labor_avg,
                    "conversion_factor": selector.unit_conversion_factor(unit_code, component_selection.unit_code),
                },
            )
        for row in component_rows:
            if not isinstance(row, dict):
                continue
            key = (row.get("rate_item_id"), row.get("rate_mapping_id"), component_code)
            if key in seen:
                continue
            seen.add(key)
            enriched = dict(row)
            enriched.setdefault("conversion_factor", selector.unit_conversion_factor(unit_code, enriched.get("unit_code")))
            enriched["candidate_scope"] = "package_component"
            enriched["package_operation_code"] = package_code
            enriched["component_operation_code"] = component_code
            enriched["component_selection_result"] = (
                component_selection.review_reason
                or ("auto_applicable" if component_selection.rate_auto_applicable else None)
            )
            enriched["component_selection_sub_reason"] = component_selection.review_sub_reason
            enriched["limitation"] = (
                "Ставка относится только к компоненту пакета; полный цикл нужно разложить "
                "на опалубку, арматуру, бетонирование и распалубку либо подтвердить частичный расчёт."
            )
            candidates.append(enriched)
    def sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, int]:
        component = str(candidate.get("component_operation_code") or "")
        same_unit = bool(unit_code and candidate.get("unit_code") == unit_code)
        has_labor = candidate.get("labor_avg") is not None
        rejected = bool(candidate.get("rejected_reason"))
        concrete_for_volume = bool(unit_code == "m3" and component == "concrete_placement")
        return (
            0 if same_unit else 1,
            0 if concrete_for_volume else 1,
            0 if has_labor else 1,
            1 if rejected else 0,
        )

    candidates.sort(key=sort_key)
    return candidates[:10]


@lru_cache(maxsize=4)
def _load_work_rate_catalog_cached(path_text: str):
    from app.services.work_rate_catalog_service import WorkRateCatalog

    return WorkRateCatalog.load(path_text)


@lru_cache(maxsize=1)
def _work_rate_operation_packages() -> dict[str, Any]:
    from app.services.work_taxonomy_service import _load_dictionary, _tz_operation_package_additions

    packages = dict((_load_dictionary().get("operation_object_resolution_policy") or {}).get("operation_packages") or {})
    packages.update(_tz_operation_package_additions())
    return packages


async def _attach_session_subtype_rate_projection(
    db: AsyncSession,
    session_id: str,
    rows: list[KtpSessionSubtype],
) -> None:
    if not rows:
        return

    catalog_path = resolve_config_path(settings.WORK_RATE_CATALOG_PATH)
    if not catalog_path.exists():
        for row in rows:
            _clear_rate_projection(row, "catalog_labor_not_available")
        return

    from app.services.work_rate_import_service import normalize_unit as normalize_work_rate_unit
    from app.services.work_rate_selection_service import WorkRateSelectionService
    from app.services.work_taxonomy_service import detect_operation_detailed

    catalog = _load_work_rate_catalog_cached(str(catalog_path))
    if not catalog.items or not catalog.mappings:
        for row in rows:
            _clear_rate_projection(row, "catalog_labor_not_available")
        return

    session = await db.get(KtpEstimateSession, session_id)
    batch = await db.get(EstimateBatch, session.estimate_batch_id) if session else None
    hours_per_day = float(batch.hours_per_day) if batch and batch.hours_per_day else 8.0
    batch_crew = int(batch.workers_count) if batch and batch.workers_count else None
    project_variant_id = None

    item_ids = [row.item_id for row in rows if row.item_id]
    items_by_id: dict[str, KtpWbsItem] = {}
    estimates_by_id: dict[str, Estimate] = {}
    if item_ids:
        items = list(await db.scalars(select(KtpWbsItem).where(KtpWbsItem.id.in_(item_ids))))
        items_by_id = {str(item.id): item for item in items}
        estimate_ids = [item.estimate_id for item in items if item.estimate_id]
        if estimate_ids:
            estimates = list(await db.scalars(select(Estimate).where(Estimate.id.in_(estimate_ids))))
            estimates_by_id = {str(estimate.id): estimate for estimate in estimates}
            project_variant_id = next((estimate.project_variant_id for estimate in estimates if estimate.project_variant_id), None)

    selector = WorkRateSelectionService(_work_rate_operation_packages())
    item_by_rate_id = {item.id: item for item in catalog.items if item.is_active}
    source_by_id = {source.id: source for source in catalog.sources if source.is_active}

    for row in rows:
        stored_operator_selection = _stored_operator_rate_selection(row) if row.output_source == "manual" else {}
        operator_selected_rate_item_id = stored_operator_selection.get("selected_rate_item_id")
        operator_selected_rate_mapping_id = stored_operator_selection.get("selected_rate_mapping_id")
        if row.crew_size is None and batch_crew is not None:
            row.crew_size = batch_crew
            row.crew_source = "estimate"
        item = items_by_id.get(str(row.item_id)) if row.item_id else None
        estimate = estimates_by_id.get(str(item.estimate_id)) if item and item.estimate_id else None
        raw = estimate.raw_data if estimate and isinstance(estimate.raw_data, dict) else {}

        taxonomy_code = (
            row.work_subtype_code
            or (item.work_subtype_code if item else None)
            or (estimate.work_subtype_code if estimate else None)
            or base_subtype_code(row.subtype_code)
        )
        operation_code = (
            getattr(item, "operation_code", None)
            or raw.get("operation_code")
            or raw.get("selected_operation_code")
        )
        operation_code = str(operation_code or "").strip() or None
        row_project_variant_id = (
            raw.get("project_variant_id")
            or (estimate.project_variant_id if estimate else None)
            or project_variant_id
        )
        section_title = raw.get("section_title") or (estimate.section if estimate else None)
        section_description = raw.get("section_description")
        unit_code, _dimension, _factor = normalize_work_rate_unit(
            (item.unit if item and item.unit else None)
            or (estimate.unit if estimate else None)
            or row.unit
        )
        detected_operations: list[str] = []

        operation_sub_reason: str | None = None
        if not operation_code and item:
            detected = detect_operation_detailed(
                item.name,
                project_variant_id=row_project_variant_id,
                section_title=section_title,
                section_description=section_description,
                unit_code=unit_code,
            )
            operation_code = detected.operation_code
            operation_sub_reason = detected.reason
            detected_operations = [
                code
                for code in [
                    detected.operation_code,
                    getattr(detected, "suggested_operation_code", None),
                    *list(detected.multi_operation_codes or ()),
                ]
                if code
            ]
        elif operation_code:
            detected_operations = [operation_code]

        if not taxonomy_code or taxonomy_code == UNKNOWN_SUBTYPE_CODE or not operation_code:
            reason = "operation_resolution_failed"
            sub_reason = (
                "operation_mapping_missing"
                if not operation_code
                else "taxonomy_mapping_missing"
            )
            if operation_sub_reason in {
                "multi_operation_row_requires_package_or_split",
                "work_operation_ambiguous",
            }:
                sub_reason = (
                    "multi_operation_row_requires_package_or_split"
                    if operation_sub_reason == "multi_operation_row_requires_package_or_split"
                    else "ambiguous_atomic_operations"
                )
            _clear_rate_projection(row, reason)
            row.item_unit_code = unit_code
            row.rate_trace = {
                "source_row_text": item.name if item else row.subtype_name,
                "detected_operations": detected_operations,
                "rate_candidates": [],
                "selection_result": reason,
                "selection_sub_reason": sub_reason,
            }
            continue

        quantity = _float_or_none(item.quantity if item else None) or _float_or_none(row.volume)
        confirmed_conversion = _confirmed_rate_unit_conversion(
            getattr(row, "rate_unit_conversion", None),
            source_unit=unit_code,
        )
        unit_conversion_overrides = (
            {
                (unit_code, confirmed_conversion["target_unit"]): confirmed_conversion["conversion_factor"],
            }
            if confirmed_conversion and unit_code
            else None
        )
        rate_applicability = {
            "project_variant_id": row_project_variant_id,
            "template_stage_number": raw.get("template_stage_number") or raw.get("work_stage_number"),
            "semantic_stage_option_id": raw.get("semantic_stage_option_id") or raw.get("preferred_stage_option_id"),
            "floor_number": raw.get("floor_number"),
            "floor_kind": raw.get("floor_kind"),
            "rate_context_code": raw.get("rate_context_code"),
        }
        selection = selector.select_rate(
            taxonomy_code=str(taxonomy_code),
            operation_code=str(operation_code),
            object_scope_code=raw.get("selected_object_scope_code") or raw.get("object_scope_code"),
            quantity=quantity,
            unit_code=unit_code,
            work_name=(item.name if item else None) or row.subtype_name,
            item_text=raw.get("item_text"),
            spec=raw.get("spec"),
            section_title=section_title,
            section_description=section_description,
            section_parent_context=raw.get("section_parent_context"),
            items=catalog.items,
            mappings=catalog.mappings,
            sources=catalog.sources,
            applicability=rate_applicability,
            unit_conversion_overrides=unit_conversion_overrides,
        )
        rate_item = item_by_rate_id.get(selection.rate_item_id) if selection.rate_item_id else None
        conversion_factor = (
            WorkRateSelectionService.unit_conversion_factor(unit_code, selection.unit_code)
            if selection.unit_code
            else None
        )
        if conversion_factor is None and confirmed_conversion and selection.unit_code == confirmed_conversion["target_unit"]:
            conversion_factor = confirmed_conversion["conversion_factor"]
        suggested_conversion = (
            _suggest_rate_unit_conversion(
                text=" ".join(str(part or "") for part in (item.name if item else None, raw.get("item_text"), raw.get("spec"))),
                source_quantity=quantity,
                source_unit=unit_code,
                target_unit=selection.unit_code,
                operation_code=selection.operation_code or operation_code,
            )
            if selection.review_reason == "unit_incompatible"
            else None
        )
        calculation = (
            WorkRateSelectionService.calculate_labor(
                quantity=quantity,
                quantity_unit=unit_code,
                rate_item=rate_item,
                unit_conversion_factor_override=conversion_factor,
            )
            if rate_item is not None
            else {}
        )
        effective_min = _per_item_labor(
            selection.labor_min,
            norm_base_quantity=selection.norm_base_quantity,
            unit_conversion_factor=conversion_factor,
        )
        effective_avg = _per_item_labor(
            selection.labor_avg,
            norm_base_quantity=selection.norm_base_quantity,
            unit_conversion_factor=conversion_factor,
        )
        effective_max = _per_item_labor(
            selection.labor_max,
            norm_base_quantity=selection.norm_base_quantity,
            unit_conversion_factor=conversion_factor,
        )
        candidate_rows = list(selection.candidates or [])
        package_component_candidates = []
        if selection.review_sub_reason == "package_expansion_required":
            package_component_candidates = _package_component_rate_candidates(
                selector=selector,
                package_code=selection.operation_code or operation_code,
                taxonomy_code=str(taxonomy_code),
                object_scope_code=raw.get("selected_object_scope_code") or raw.get("object_scope_code"),
                quantity=quantity,
                unit_code=unit_code,
                work_name=(item.name if item else None) or row.subtype_name,
                item_text=raw.get("item_text"),
                spec=raw.get("spec"),
                section_title=section_title,
                section_description=section_description,
                section_parent_context=raw.get("section_parent_context"),
                catalog=catalog,
                applicability=rate_applicability,
                unit_conversion_overrides=unit_conversion_overrides,
            )
            candidate_rows.extend(package_component_candidates)
        if rate_item is not None and not any(c.get("rate_item_id") == rate_item.id for c in candidate_rows if isinstance(c, dict)):
            candidate_rows.insert(
                0,
                {
                    "rate_item_id": rate_item.id,
                    "rate_mapping_id": selection.rate_mapping_id,
                    "name": rate_item.name,
                    "unit_code": rate_item.unit_code,
                    "norm_base_quantity": rate_item.norm_base_quantity,
                    "rate_context_code": selection.rate_context_code,
                    "labor_avg": rate_item.labor_avg,
                    "conversion_factor": conversion_factor,
                },
            )
        trace_candidates: list[dict[str, Any]] = []
        for candidate in candidate_rows[:10]:
            if not isinstance(candidate, dict):
                continue
            candidate_item = item_by_rate_id.get(candidate.get("rate_item_id"))
            candidate_conversion = candidate.get("conversion_factor")
            if candidate_conversion is None and candidate_item is not None:
                candidate_conversion = WorkRateSelectionService.unit_conversion_factor(unit_code, candidate_item.unit_code)
            display_conversion = (
                candidate_conversion
                if candidate_conversion is not None
                else (1.0 if candidate_item is not None else None)
            )
            normalized_candidate_value = _per_item_labor(
                getattr(candidate_item, "labor_avg", None) if candidate_item is not None else candidate.get("labor_avg"),
                norm_base_quantity=(
                    getattr(candidate_item, "norm_base_quantity", None)
                    if candidate_item is not None
                    else candidate.get("norm_base_quantity")
                ),
                unit_conversion_factor=display_conversion,
            )
            source = source_by_id.get(candidate_item.source_id) if candidate_item is not None else None
            trace_candidate = _rate_candidate_trace(
                candidate=candidate,
                rate_item=candidate_item,
                rate_mapping_id=candidate.get("rate_mapping_id"),
                source=source,
                normalized_value=normalized_candidate_value,
            )
            for key in (
                "candidate_scope",
                "package_operation_code",
                "component_operation_code",
                "component_selection_result",
                "component_selection_sub_reason",
                "limitation",
                "rejected_reason",
            ):
                if candidate.get(key) is not None:
                    trace_candidate[key] = candidate.get(key)
            trace_candidates.append(trace_candidate)
            for code in trace_candidate.get("all_target_codes") or []:
                if code and code not in detected_operations:
                    detected_operations.append(code)

        catalog_total = calculation.get("labor_avg_total")
        resolved_labor_hours = catalog_total if selection.rate_auto_applicable else None
        resolved_labor_source = "catalog_independent" if resolved_labor_hours else None

        _set_row_projection_attr(row, "selected_rate_item_id", operator_selected_rate_item_id or selection.rate_item_id)
        _set_row_projection_attr(row, "selected_rate_mapping_id", operator_selected_rate_mapping_id or selection.rate_mapping_id)
        row.rate_unit_code = selection.unit_code
        row.item_unit_code = unit_code
        row.unit_conversion_factor = conversion_factor
        row.labor_hours_per_unit_min = selection.labor_min
        row.labor_hours_per_unit_avg = selection.labor_avg
        row.labor_hours_per_unit_max = selection.labor_max
        row.effective_labor_hours_per_unit_min = effective_min
        row.effective_labor_hours_per_unit_avg = effective_avg
        row.effective_labor_hours_per_unit_max = effective_max
        row.session_calculated_labor_hours_min = calculation.get("labor_min_total")
        row.session_calculated_labor_hours_avg = calculation.get("labor_avg_total")
        row.session_calculated_labor_hours_max = calculation.get("labor_max_total")
        row.rate_auto_applicable = bool(selection.rate_auto_applicable)
        row.rate_needs_review = bool(selection.needs_review)
        row.rate_review_reason = selection.review_reason
        row.resolved_labor_source = resolved_labor_source
        row.resolved_labor_hours = resolved_labor_hours
        row.rate_catalog_version = str(
            catalog.metadata.get("rate_catalog_version")
            or catalog.metadata.get("catalog_version")
            or getattr(catalog, "FORMAT_VERSION", "1.4.0")
        )
        row.rate_catalog_file = catalog_path.name
        row.rate_trace = {
            "source_row_text": item.name if item else row.subtype_name,
            "taxonomy_code": str(taxonomy_code),
            "operation_code": selection.operation_code or operation_code,
            "detected_operations": detected_operations,
            "rate_candidates": trace_candidates,
            "selection_result": selection.review_reason or ("auto_applicable" if selection.rate_auto_applicable else None),
            "selection_sub_reason": selection.review_sub_reason,
            "rate_unit_conversion": confirmed_conversion or getattr(row, "rate_unit_conversion", None) or suggested_conversion,
            "conversion_required": selection.review_reason == "unit_incompatible",
        }
        if operator_selected_rate_item_id or operator_selected_rate_mapping_id:
            row.rate_trace["operator_selection"] = {
                "selected_rate_item_id": operator_selected_rate_item_id,
                "selected_rate_mapping_id": operator_selected_rate_mapping_id,
                "output_per_day": stored_operator_selection.get("output_per_day", row.output_per_day),
            }

        if (
            selection.rate_auto_applicable
            and row.output_source != "manual"
            and effective_avg is not None
        ):
            output_per_day = WorkRateSelectionService.output_per_day(
                crew_size=row.crew_size,
                hours_per_day=hours_per_day,
                labor_hours_per_unit=effective_avg,
            )
            if output_per_day is not None:
                row.output_per_day = output_per_day
                row.output_source = "catalog"


async def build_session_subtypes(
    db: AsyncSession, session: KtpEstimateSession
) -> list[KtpSessionSubtype]:
    """Построить/обновить таблицу производительности сессии из принятых работ КТП.

    Одна строка = одна работа (``item``) «как есть» — ничего не схлопываем, чтобы
    разные работы одного грубого подтипа не сливались и не терялись. Подтип из
    справочника читается с ``KtpWbsItem.work_subtype_code``; он даёт дефолты
    (производительность/бригада/пауза) и контекст (код, macro). ``volume``
    берётся из объёма работы; правки оператора (``*_source='manual'``) не
    перезатираются. Исчезнувшие работы удаляются.
    """
    from app.services.work_taxonomy_service import load_taxonomy

    groups = list(
        await db.scalars(
            select(KtpWbsGroup)
            .where(KtpWbsGroup.session_id == session.id)
            .options(selectinload(KtpWbsGroup.items))
        )
    )
    items = [
        it
        for g in groups
        for it in g.items
        if it.review_status != "rejected"
    ]

    estimate_ids = [it.estimate_id for it in items if it.estimate_id]
    estimates: dict[str, Estimate] = {}
    if estimate_ids:
        estimates = {
            e.id: e
            for e in await db.scalars(
                select(Estimate).where(Estimate.id.in_(estimate_ids))
            )
        }

    taxonomy = await load_taxonomy(db)
    subtypes_by_code = {
        s.code: s for s in await db.scalars(select(WorkSubtype))
    }

    # Размер бригады задаётся при загрузке сметы (EstimateBatch.workers_count) —
    # берём его как дефолт вместо справочника.
    batch = await db.get(EstimateBatch, session.estimate_batch_id)
    batch_crew = (
        int(batch.workers_count)
        if batch and batch.workers_count
        else None
    )

    existing = {
        (s.subtype_code, s.unit): s
        for s in await _load_session_subtypes(db, session.id)
    }

    # Бригада: приоритет — значение из загрузки сметы; иначе справочник.
    def _crew_default(ref: WorkSubtype | None) -> tuple[int | None, str]:
        if batch_crew is not None:
            return batch_crew, "estimate"
        return (ref.crew_size if ref else None), "default"

    # Одна строка = одна работа. Ключ уникален по item.id (закодирован в
    # subtype_code), поэтому разные работы не сливаются.
    kept_keys: set[tuple[str, str | None]] = set()
    for it in items:
        est = estimates.get(it.estimate_id) if it.estimate_id else None
        base_code, sub_name, macro_name, unit = _resolve_item_subtype(
            it, est, taxonomy, subtypes_by_code
        )
        ref = subtypes_by_code.get(base_code)  # None для работ без подтипа
        stored_code = session_subtype_code(it, base_code)
        display_name = sub_name or (it.name or "").strip() or base_code
        volume = (
            float(it.quantity)
            if it.quantity is not None and float(it.quantity) > 0
            else _DEFAULT_VOLUME
        )
        crew_value, crew_src = _crew_default(ref)
        key = (stored_code, unit)
        kept_keys.add(key)
        row = existing.get(key)
        if row is None:
            row = KtpSessionSubtype(
                id=_uuid(),
                session_id=session.id,
                subtype_code=stored_code,
                subtype_name=display_name,
                work_subtype_code=base_code,
                work_subtype_name=sub_name,
                item_id=it.id,
                session_subtype_key=stored_code,
                macro_name=macro_name,
                unit=unit,
                volume=volume,
                output_per_day=ref.output_per_day if ref else None,
                crew_size=crew_value,
                lag_after_days=int(ref.lag_after_days) if ref else 0,
                output_source="default",
                crew_source=crew_src,
                lag_source="default",
            )
            db.add(row)
        else:
            # имя/подтип/объём — всегда из актуальных данных работы
            row.subtype_name = display_name
            row.work_subtype_code = base_code
            row.work_subtype_name = sub_name
            row.item_id = it.id
            row.session_subtype_key = stored_code
            row.macro_name = macro_name
            row.volume = volume
            # дефолтные поля обновляем из источника, ручные правки не трогаем
            if row.output_source == "default" and ref is not None:
                row.output_per_day = ref.output_per_day
            if row.crew_source != "manual":
                row.crew_size = crew_value
                row.crew_source = crew_src
            if row.lag_source == "default" and ref is not None:
                row.lag_after_days = int(ref.lag_after_days)

    # Удаляем строки, которых больше нет в смете.
    for key, row in existing.items():
        if key not in kept_keys:
            await db.delete(row)

    await db.flush()
    return await _load_session_subtypes(db, session.id)


async def rebuild_session_subtypes(
    db: AsyncSession, project_id: str, session_id: str
) -> dict[str, Any]:
    session = await get_session_by_id(db, project_id, session_id)
    if session.status not in {"prod_pending", "prod_review"}:
        raise ValueError("Перестроить подтипы можно только на этапе производительности")
    await build_session_subtypes(db, session)
    await db.commit()
    return await get_wbs(db, project_id, session_id)


async def update_session_subtype(
    db: AsyncSession,
    project_id: str,
    subtype_id: str,
    patch: dict[str, Any],
    user_id: str | None = None,
) -> dict[str, Any]:
    row = await db.scalar(
        select(KtpSessionSubtype)
        .join(KtpEstimateSession, KtpEstimateSession.id == KtpSessionSubtype.session_id)
        .where(KtpSessionSubtype.id == subtype_id)
        .where(KtpEstimateSession.project_id == project_id)
    )
    if not row:
        raise ValueError("Подтип работ не найден")

    if "volume" in patch:
        v = patch["volume"]
        if v is not None and float(v) <= 0:
            raise ValueError("Объём должен быть больше нуля")
        row.volume = float(v) if v is not None else None
    if "output_per_day" in patch:
        v = patch["output_per_day"]
        if v is not None and float(v) <= 0:
            raise ValueError("Производительность должна быть больше нуля")
        row.output_per_day = float(v) if v is not None else None
        row.output_source = "manual"
        selected_rate_item_id = (
            str(patch["selected_rate_item_id"] or "").strip()
            if "selected_rate_item_id" in patch
            else str(_stored_operator_rate_selection(row).get("selected_rate_item_id") or "").strip()
        ) or None
        selected_rate_mapping_id = (
            str(patch["selected_rate_mapping_id"] or "").strip()
            if "selected_rate_mapping_id" in patch
            else str(_stored_operator_rate_selection(row).get("selected_rate_mapping_id") or "").strip()
        ) or None
        _set_row_projection_attr(row, "selected_rate_item_id", selected_rate_item_id)
        _set_row_projection_attr(row, "selected_rate_mapping_id", selected_rate_mapping_id)
        if selected_rate_item_id or selected_rate_mapping_id:
            stored_conversion = row.rate_unit_conversion if isinstance(row.rate_unit_conversion, dict) else {}
            stored_conversion = dict(stored_conversion)
            stored_conversion["operator_selection"] = {
                "selected_rate_item_id": selected_rate_item_id,
                "selected_rate_mapping_id": selected_rate_mapping_id,
                "output_per_day": row.output_per_day,
                "confirmed_by_user_id": user_id,
                "confirmed_at": _now().isoformat(),
            }
            row.rate_unit_conversion = stored_conversion
            flag_modified(row, "rate_unit_conversion")
            trace = row.rate_trace if isinstance(row.rate_trace, dict) else {}
            trace["operator_selection"] = stored_conversion["operator_selection"]
            row.rate_trace = trace
        if row.output_per_day is not None and row.item_id:
            item = await db.get(KtpWbsItem, row.item_id)
            if item and (item.operator_review_required or item.work_type_needs_review):
                item.gpr_confirmed = True
    if "crew_size" in patch:
        v = patch["crew_size"]
        if v is not None and int(v) <= 0:
            raise ValueError("Размер бригады должен быть больше нуля")
        row.crew_size = int(v) if v is not None else None
        row.crew_source = "manual"
    if "lag_after_days" in patch:
        v = patch["lag_after_days"]
        if v is None or int(v) < 0:
            raise ValueError("Лаг не может быть отрицательным")
        row.lag_after_days = int(v)
        row.lag_source = "manual"
    if "rate_unit_conversion" in patch:
        payload = patch["rate_unit_conversion"]
        if payload is None:
            row.rate_unit_conversion = None
        elif not isinstance(payload, dict):
            raise ValueError("Параметры конвертации должны быть объектом")
        else:
            status = payload.get("conversion_status")
            if status != "user_confirmed":
                raise ValueError("Конвертация должна быть подтверждена пользователем")
            factor = _float_or_none(payload.get("conversion_factor"))
            derived_quantity = _float_or_none(payload.get("derived_quantity"))
            target_unit = str(payload.get("target_unit") or "").strip()
            input_unit = str(payload.get("input_unit") or payload.get("source_unit") or "").strip()
            if factor is None:
                raise ValueError("Коэффициент конвертации должен быть больше нуля")
            if derived_quantity is None:
                raise ValueError("Расчётное количество должно быть больше нуля")
            if not input_unit or not target_unit:
                raise ValueError("Укажите исходную и целевую единицу конвертации")
            clean_payload = dict(payload)
            clean_payload["conversion_status"] = "user_confirmed"
            clean_payload["input_unit"] = input_unit
            clean_payload["source_unit"] = input_unit
            clean_payload["target_unit"] = target_unit
            clean_payload["conversion_factor"] = factor
            clean_payload["derived_quantity"] = derived_quantity
            clean_payload["confirmed_by_user_id"] = user_id
            clean_payload["confirmed_at"] = _now().isoformat()
            row.rate_unit_conversion = clean_payload
        row.output_per_day = None
        row.output_source = "default"

    row.updated_at = _now()
    await db.commit()
    return await get_wbs(db, project_id, row.session_id)


async def approve_prod(
    db: AsyncSession,
    project_id: str,
    session_id: str,
) -> KtpEstimateSession:
    session = await get_session_by_id(db, project_id, session_id)
    if session.status not in {"prod_pending", "prod_review"}:
        raise ValueError("К ГПР можно перейти после этапа производительности")

    rows = await _load_session_subtypes(db, session_id)
    if not rows:
        raise ValueError("Таблица подтипов пуста — перестройте её из сметы")
    missing = [
        r.subtype_name
        for r in rows
        if r.output_per_day is None or float(r.output_per_day) <= 0
        or r.volume is None or float(r.volume) <= 0
    ]
    if missing:
        preview = ", ".join(missing[:5])
        raise ValueError(
            f"Не у всех подтипов задана производительность и объём: {preview}"
        )

    items = list(
        await db.scalars(
            select(KtpWbsItem)
            .where(KtpWbsItem.session_id == session_id)
            .where(KtpWbsItem.review_status != "rejected")
        )
    )
    blockers = [it.name for it in items if gpr_blocker(it)]
    if blockers:
        preview = ", ".join(blockers[:5])
        raise ValueError(f"Есть работы, требующие проверки перед ГПР: {preview}")

    session.status = "gpr_pending"
    session.error_message = None
    session.updated_at = _now()
    await db.commit()
    await db.refresh(session)
    return session


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 2.5 — НАЗНАЧЕНИЕ ФЕР ПОЗИЦИЯМ КТП (legacy, выведено из потока)
# ─────────────────────────────────────────────────────────────────────────────

async def start_fer_match_job(
    db: AsyncSession,
    project_id: str,
    session_id: str,
    user_id: str,
) -> Job:
    session = await get_session_by_id(db, project_id, session_id)
    if session.status not in {"fer_pending", "fer_review", "fer_failed"}:
        raise ValueError("ФЕР можно назначать только после утверждения карточек КТП")

    job = Job(
        id=_uuid(),
        type="ktp_fer_match",
        status="pending",
        project_id=project_id,
        created_by=user_id,
        input={"session_id": session_id},
    )
    db.add(job)
    await db.flush()
    session.gpr_job_id = job.id
    session.status = "fer_processing"
    session.error_message = None
    await db.commit()

    asyncio.create_task(_process_fer_match(job.id))
    return job


async def _process_fer_match(job_id: str) -> None:
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
        session.status = "fer_processing"
        await db.commit()

        async def _progress(msg: str) -> None:
            job.result = {"_progress": msg}
            await db.commit()

        try:
            batch = await db.get(EstimateBatch, session.estimate_batch_id)
            groups = list(
                await db.scalars(
                    select(KtpWbsGroup)
                    .where(KtpWbsGroup.session_id == session_id)
                    .options(selectinload(KtpWbsGroup.items))
                    .order_by(KtpWbsGroup.sort_order)
                )
            )
            groups = [
                g
                for g in groups
                if any(it.review_status != "rejected" for it in g.items)
            ]
            if not groups:
                raise ValueError("В КТП нет принятых работ для назначения ФЕР")

            items = [it for g in groups for it in g.items if it.review_status != "rejected"]
            await _progress("Назначаем ФЕР по группам КТП…")
            fer_stats = await match_session_items(
                db,
                session,
                batch.estimate_kind if batch else 1,
                groups,
                items,
                _progress,
            )

            session.status = "fer_review"
            session.error_message = None
            job.status = "done"
            job.result = {"session_id": session_id, "fer_match_stats": fer_stats}
        except Exception as exc:  # noqa: BLE001
            logger.exception("KTP FER match failed for job %s", job_id)
            session.status = "fer_failed"
            session.error_message = str(exc)
            job.status = "failed"
            job.result = {"error": str(exc)}
        finally:
            job.finished_at = datetime.utcnow()
            await db.commit()


async def _apply_manual_fer_table(
    db: AsyncSession,
    item: KtpWbsItem,
    fer_table_id: int | None,
) -> None:
    if fer_table_id is None:
        item.fer_table_id = None
        item.fer_row_id = None
        item.fer_match_source = None
        item.fer_match_score = None
        item.fer_match_candidates = None
        item.fer_h_hour = None
        item.fer_unit = None
        item.fer_unit_multiplier = None
        return

    row = (
        await db.execute(
            text(
                """
                SELECT
                    t.id,
                    t.table_title,
                    t.common_work_name,
                    COALESCE(SUM(fr.h_hour), 0) AS h_hour,
                    (
                        COALESCE(c.ignored, FALSE)
                        OR COALESCE(s.ignored, FALSE)
                        OR COALESCE(ss.ignored, FALSE)
                        OR COALESCE(t.ignored, FALSE)
                    ) AS effective_ignored
                FROM fer.fer_tables t
                JOIN fer.collections c ON c.id = t.collection_id
                LEFT JOIN fer.sections s ON s.id = t.section_id
                LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
                LEFT JOIN fer.fer_rows fr ON fr.table_id = t.id
                WHERE t.id = :table_id
                GROUP BY t.id, t.table_title, t.common_work_name, c.ignored, s.ignored, ss.ignored, t.ignored
                """
            ),
            {"table_id": fer_table_id},
        )
    ).mappings().first()
    if row is None:
        raise ValueError("Таблица ФЕР не найдена")
    if row.get("effective_ignored"):
        raise ValueError("Таблица ФЕР помечена как игнорируемая")

    work_type = (row["common_work_name"] or "").strip() or str(row["table_title"]).strip()
    fer_unit, multiplier = extract_fer_unit(str(row["table_title"]))
    item_unit = normalize_unit(item.unit)

    item.fer_table_id = int(row["id"])
    item.fer_row_id = None
    item.fer_match_source = "manual"
    item.fer_match_score = 1.0
    item.fer_match_candidates = [
        {
            "table_id": int(row["id"]),
            "row_id": None,
            "work_type": work_type,
            "final_score": 1.0,
        }
    ]
    h_hour = float(row["h_hour"]) if row["h_hour"] is not None else None
    item.fer_h_hour = h_hour if h_hour and h_hour > 0 else None
    item.fer_unit = fer_unit
    item.fer_unit_multiplier = (
        multiplier
        if fer_unit is not None and item_unit is not None and fer_unit == item_unit
        else None
    )


async def update_item_fer(
    db: AsyncSession,
    project_id: str,
    item_id: str,
    fer_table_id: int | None,
) -> dict[str, Any]:
    item = await db.scalar(
        select(KtpWbsItem)
        .join(KtpWbsGroup, KtpWbsGroup.id == KtpWbsItem.group_id)
        .where(KtpWbsItem.id == item_id)
        .where(KtpWbsGroup.project_id == project_id)
    )
    if not item:
        raise ValueError("Позиция КТП не найдена")
    await _apply_manual_fer_table(db, item, fer_table_id)
    session = await db.get(KtpEstimateSession, item.session_id)
    if session and session.status in {"fer_pending", "fer_failed"}:
        session.status = "fer_review"
    await db.commit()
    return await get_wbs(db, project_id, item.session_id)


async def auto_match_item_fer(
    db: AsyncSession,
    project_id: str,
    item_id: str,
) -> dict[str, Any]:
    item = await db.scalar(
        select(KtpWbsItem)
        .join(KtpWbsGroup, KtpWbsGroup.id == KtpWbsItem.group_id)
        .where(KtpWbsItem.id == item_id)
        .where(KtpWbsGroup.project_id == project_id)
    )
    if not item:
        raise ValueError("Позиция КТП не найдена")
    group = await db.get(KtpWbsGroup, item.group_id)
    session = await db.get(KtpEstimateSession, item.session_id)
    batch = await db.get(EstimateBatch, session.estimate_batch_id) if session else None
    if not group or not session or not batch:
        raise ValueError("Контекст позиции КТП не найден")
    await match_session_items(db, session, batch.estimate_kind, [group], [item], None)
    if session.status in {"fer_pending", "fer_failed"}:
        session.status = "fer_review"
    await db.commit()
    return await get_wbs(db, project_id, item.session_id)


async def approve_fer_matches(
    db: AsyncSession,
    project_id: str,
    session_id: str,
) -> KtpEstimateSession:
    session = await get_session_by_id(db, project_id, session_id)
    if session.status not in {"fer_review", "fer_pending", "fer_failed"}:
        raise ValueError("К ГПР можно перейти после этапа назначения ФЕР")
    session.status = "gpr_pending"
    session.error_message = None
    session.updated_at = _now()
    await db.commit()
    await db.refresh(session)
    return session


# ─────────────────────────────────────────────────────────────────────────────
# ПОСЛЕДОВАТЕЛЬНОСТЬ ГРУПП (подшаг ГПР, 2-й уровень) — ревьюемый порядок
# ─────────────────────────────────────────────────────────────────────────────

_SEQUENCE_ALLOWED_STATUSES = {
    "gpr_pending",
    "gpr_sequence_review",
    "gpr_ready",
    "gpr_failed",
    "gpr_done",
}


def _is_fallback_group_title(title: str | None) -> bool:
    return (title or "").strip() in {FALLBACK_DISPLAY_TITLE, FALLBACK_GROUP_TITLE}


async def _load_session_groups(
    db: AsyncSession, session_id: str
) -> list[KtpWbsGroup]:
    return list(
        await db.scalars(
            select(KtpWbsGroup)
            .where(KtpWbsGroup.session_id == session_id)
            .order_by(KtpWbsGroup.sort_order, KtpWbsGroup.created_at)
        )
    )


def _reassign_sequence_sort_order(
    ordered_normal: list[KtpWbsGroup],
    fallback_groups: list[KtpWbsGroup],
) -> None:
    """Линейный порядок: обычные группы 1000, 2000, …; fallback всегда в конце."""
    step = 1000.0
    order = step
    for g in ordered_normal:
        g.sort_order = order
        g.updated_at = _now()
        order += step
    for g in fallback_groups:
        g.sort_order = order
        g.updated_at = _now()
        order += step


async def propose_group_sequence(
    db: AsyncSession, project_id: str, session_id: str
) -> dict[str, Any]:
    """ИИ выстраивает технологическую последовательность групп (линейный порядок).

    Fallback-группа «прочих» работ всегда ставится в конец списка. Результат —
    обновлённый sort_order; статус сессии → gpr_sequence_review. Оператор затем
    правит порядок вручную (PATCH /groups/{id}) и подтверждает approve-sequence.
    """
    from app.services.ktp_gpr_service import _ai_order_groups

    session = await get_session_by_id(db, project_id, session_id)
    if session.status not in _SEQUENCE_ALLOWED_STATUSES:
        raise ValueError(
            "Последовательность групп можно строить только после утверждения "
            "карточек КТП (этап 2)"
        )

    groups = await _load_session_groups(db, session_id)
    normal = [g for g in groups if not _is_fallback_group_title(g.title)]
    fallback = [g for g in groups if _is_fallback_group_title(g.title)]

    if normal:
        ordered_ids = await _ai_order_groups(normal)
        by_id = {g.id: g for g in normal}
        ordered_normal = [by_id[gid] for gid in ordered_ids if gid in by_id]
        # добор на случай, если что-то не вернулось из упорядочивания
        for g in normal:
            if g not in ordered_normal:
                ordered_normal.append(g)
    else:
        ordered_normal = []

    _reassign_sequence_sort_order(ordered_normal, fallback)

    session.status = "gpr_sequence_review"
    session.updated_at = _now()
    await db.commit()
    return await get_wbs(db, project_id, session_id)


async def approve_group_sequence(
    db: AsyncSession, project_id: str, session_id: str
) -> KtpEstimateSession:
    """Фиксирует порядок групп. Fallback-группа принудительно ставится в конец."""
    session = await get_session_by_id(db, project_id, session_id)
    if session.status not in {"gpr_sequence_review", "gpr_ready", "gpr_pending"}:
        raise ValueError("Нет последовательности групп для утверждения")

    groups = await _load_session_groups(db, session_id)
    fallback = [g for g in groups if _is_fallback_group_title(g.title)]
    if fallback:
        max_normal = max(
            (
                float(g.sort_order)
                for g in groups
                if not _is_fallback_group_title(g.title)
            ),
            default=0.0,
        )
        order = max_normal + 1000.0
        for g in fallback:
            g.sort_order = order
            g.updated_at = _now()
            order += 1000.0

    session.status = "gpr_ready"
    session.updated_at = _now()
    await db.commit()
    await db.refresh(session)
    return session
