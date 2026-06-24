"""Этап 3 — построение ГПР (график производства работ) из утверждённого КТП.

- Длительности: ИИ выбирает норму, КОД считает T детерминированно.
- Зависимости: ИИ упорядочивает ГРУППЫ (FS), код проверяет циклы.
- Даты: топологический прямой проход по группам.
- Результат пишется в gantt_tasks + task_dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.date_utils import next_task_start_date, task_end_date
from app.models import (
    EnirNorm,
    EnirParagraph,
    EstimateBatch,
    GanttTask,
    Job,
    KtpEstimateSession,
    KtpSessionSubtype,
    KtpWbsGroup,
    KtpWbsGroupDependency,
    KtpWbsItem,
    TaskDependency,
    WorkSubtype,
)
from app.models.estimate import Estimate
from app.services.gantt_calculations import (
    DEFAULT_HOURS_PER_DAY,
    calculate_labor_hours,
    calculate_working_days,
)
from app.services.ktp_estimate_service import gpr_blocker
from app.services.openrouter_embeddings import create_chat_completion, parse_json_object

logger = logging.getLogger(__name__)

DEFAULT_BRIGADE_SIZE = 3
MAX_DURATION_DAYS = 365

# Статусы подшага «последовательность групп» внутри фазы ГПР.
SEQUENCE_REVIEW_STATUS = "gpr_sequence_review"
SEQUENCE_READY_STATUS = "gpr_ready"

# Заголовки fallback-группы «прочих» работ (текущий + legacy).
FALLBACK_GROUP_TITLES = {"Прочие позиции сметы", "Прочие работы сметы"}


def _uuid() -> str:
    return str(uuid.uuid4())


def _is_fallback_group(title: str | None) -> bool:
    return (title or "").strip() in FALLBACK_GROUP_TITLES


# ─────────────────────────────────────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────────────────────────────────────

async def start_gpr_job(
    db: AsyncSession, project_id: str, session_id: str, user_id: str
) -> Job:
    session = await db.scalar(
        select(KtpEstimateSession)
        .where(KtpEstimateSession.id == session_id)
        .where(KtpEstimateSession.project_id == project_id)
    )
    if not session:
        raise ValueError(f"Сеанс КТП {session_id} не найден в проекте {project_id}")
    if session.status not in {
        "gpr_pending",
        SEQUENCE_REVIEW_STATUS,
        SEQUENCE_READY_STATUS,
        "gpr_processing",
        "gpr_failed",
        "gpr_done",
    }:
        raise ValueError(
            "ГПР можно строить только после утверждения карточек КТП (этап 2)"
        )

    job = Job(
        id=_uuid(),
        type="ktp_gpr_build",
        status="pending",
        project_id=project_id,
        created_by=user_id,
        input={"session_id": session_id},
    )
    db.add(job)
    # Сначала INSERT Job — иначе UPDATE сессии падает по FK.
    await db.flush()
    session.gpr_job_id = job.id
    session.status = "gpr_processing"
    await db.commit()

    asyncio.create_task(_process_gpr(job.id))
    return job


# ─────────────────────────────────────────────────────────────────────────────
# ФОНОВАЯ ОБРАБОТКА
# ─────────────────────────────────────────────────────────────────────────────

async def _process_gpr(job_id: str) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        session_id = job.input.get("session_id")
        session = await db.get(KtpEstimateSession, session_id)
        if not session:
            return

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        session.status = "gpr_processing"
        await db.commit()

        async def _progress(msg: str) -> None:
            job.result = {"_progress": msg}
            await db.commit()

        warnings: list[str] = []
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
            # только принятые работы — НЕ мутируем relationship (delete-orphan),
            # держим отдельный список на не-mapped атрибуте группы
            for g in groups:
                g.accepted_items = [
                    it for it in g.items if it.review_status != "rejected"
                ]
            groups = [g for g in groups if g.accepted_items]
            if not groups:
                raise ValueError("В КТП нет принятых работ для построения ГПР")

            blocked = [
                it for g in groups for it in g.accepted_items if gpr_blocker(it)
            ]
            if blocked:
                examples = ", ".join(str(it.name) for it in blocked[:5])
                raise ValueError(
                    "ГПР нельзя построить: есть неподтверждённые этапы, типы работ "
                    "или нормы трудоёмкости. Подтвердите позиции КТП: " + examples
                )

            hours_per_day = float(batch.hours_per_day or DEFAULT_HOURS_PER_DAY)
            default_brigade = max(1, int(batch.workers_count or DEFAULT_BRIGADE_SIZE))

            # Шаг 3 — длительности
            await _compute_durations(
                db, groups, hours_per_day, warnings, _progress, default_brigade
            )
            await _progress("Расставляем зависимости между группами…")

            # Шаг 4 — зависимости между группами
            dep_edges = await _resolve_group_dependencies(groups, warnings)
            await db.execute(
                delete(KtpWbsGroupDependency).where(
                    KtpWbsGroupDependency.group_id.in_([g.id for g in groups])
                )
            )
            for gid, dep_gid in dep_edges:
                db.add(
                    KtpWbsGroupDependency(group_id=gid, depends_on_group_id=dep_gid)
                )

            # Даты — топологический проход по группам
            start_default = batch.start_date or date.today()
            _schedule_groups(groups, dep_edges, start_default)

            # Запись в gantt_tasks
            counts = await _write_gantt(db, session, batch, groups, dep_edges)

            session.status = "gpr_done"
            session.error_message = None
            job.status = "done"
            job.result = {
                "session_id": session_id,
                "gantt_tasks_count": counts["tasks"],
                "dependency_count": counts["deps"],
                "warnings": warnings,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("KTP GPR build failed for job %s", job_id)
            session.status = "gpr_failed"
            session.error_message = str(exc)
            job.status = "failed"
            job.result = {"error": str(exc), "warnings": warnings}
        finally:
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# ШАГ 3 — ДЛИТЕЛЬНОСТИ
# ─────────────────────────────────────────────────────────────────────────────

def _apply_subtype_norm(
    it: KtpWbsItem,
    spec: KtpSessionSubtype | None,
    hours_per_day: float,
    default_brigade: int,
) -> bool:
    """Ground duration from the operator-set per-subtype productivity.

    Groundable when the item's subtype carries ``output_per_day > 0`` and we have a
    quantity. ``duration = ceil(quantity / output_per_day)``; brigade from the
    subtype's crew_size. Otherwise returns False → item falls through to _ai_pick_norms.
    """
    if spec is None or spec.output_per_day is None or float(spec.output_per_day) <= 0:
        return False
    if it.quantity is None:
        return False
    output_per_day = float(spec.output_per_day)
    quantity = float(it.quantity)
    brigade = max(1, int(spec.crew_size or it.brigade_size or default_brigade or DEFAULT_BRIGADE_SIZE))
    duration = max(1, math.ceil(quantity / output_per_day))

    it.brigade_size = brigade
    it.norm_source = "manual"
    it.norm_kind = "vyrabotka"
    it.norm_value = round(output_per_day, 4)
    it.norm_unit = (it.unit or spec.unit or "")[:32] or None
    from app.services.ktp_estimate_service import base_subtype_code

    it.norm_ref = f"подтип {base_subtype_code(spec.subtype_code)}"[:64]
    it.duration_days = max(1, min(MAX_DURATION_DAYS, int(duration)))
    it.labor_hours = float(calculate_labor_hours(it.duration_days, brigade, hours_per_day))
    return True


def _apply_precalculated_labor(
    it: KtpWbsItem,
    hours_per_day: float,
    default_brigade: int,
) -> bool:
    """Ground duration from projection-specific catalog/user labour.

    Stage 8 stores a rate per normalized base quantity.  Stage 10 calculates
    labour for every floor projection during KTP materialization.  When that
    value is present it is more reliable than subtype output or an AI estimate.
    """
    labor = getattr(it, "labor_hours", None)
    try:
        labor_value = float(labor)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(labor_value) or labor_value <= 0:
        return False
    brigade = max(1, int(getattr(it, "brigade_size", None) or default_brigade or DEFAULT_BRIGADE_SIZE))
    duration = calculate_working_days(labor_value, brigade, hours_per_day) or 1
    it.brigade_size = brigade
    it.duration_days = max(1, min(MAX_DURATION_DAYS, int(duration)))
    if not getattr(it, "norm_source", None):
        it.norm_source = "rate_catalog"
    if not getattr(it, "norm_kind", None):
        it.norm_kind = "norm_time"
    return True


async def _load_subtype_specs(
    db: AsyncSession, session_id: str
) -> dict[tuple[str, str | None], KtpSessionSubtype]:
    rows = await db.scalars(
        select(KtpSessionSubtype).where(KtpSessionSubtype.session_id == session_id)
    )
    return {(r.subtype_code, r.unit): r for r in rows}


async def _compute_durations(
    db: AsyncSession,
    groups: list[KtpWbsGroup],
    hours_per_day: float,
    warnings: list[str],
    on_progress: Callable[[str], Awaitable[None]] | None = None,
    default_brigade: int = DEFAULT_BRIGADE_SIZE,
) -> None:
    from app.services.ktp_estimate_service import (
        _resolve_item_subtype,
        session_subtype_code,
    )
    from app.services.work_taxonomy_service import load_taxonomy

    items = [it for g in groups for it in g.accepted_items]
    if not items:
        return
    session_id = items[0].session_id

    # Спецификации подтипов (производительность/бригада/лаг), заданные оператором.
    specs = await _load_subtype_specs(db, session_id)
    taxonomy = await load_taxonomy(db)
    subtypes_by_code = {s.code: s for s in await db.scalars(select(WorkSubtype))}
    estimate_ids = [it.estimate_id for it in items if it.estimate_id]
    estimates: dict[str, Estimate] = {}
    if estimate_ids:
        estimates = {
            e.id: e
            for e in await db.scalars(select(Estimate).where(Estimate.id.in_(estimate_ids)))
        }

    # Шаг 3a — длительности из производительности подтипа (без ИИ); попутно
    # запоминаем лаг подтипа на каждой группе для расстановки зависимостей.
    for g in groups:
        g.prod_lag_after = 0
    grounded: set[str] = set()
    for g in groups:
        for it in g.accepted_items:
            est = estimates.get(it.estimate_id) if it.estimate_id else None
            code, _name, _macro, unit = _resolve_item_subtype(
                it, est, taxonomy, subtypes_by_code
            )
            spec = specs.get((session_subtype_code(it, code), unit))
            if spec is not None:
                g.prod_lag_after = max(g.prod_lag_after, int(spec.lag_after_days or 0))
            if _apply_precalculated_labor(it, hours_per_day, default_brigade):
                grounded.add(it.id)
            elif _apply_subtype_norm(it, spec, hours_per_day, default_brigade):
                grounded.add(it.id)
    if grounded and on_progress:
        await on_progress(
            f"Длительность по производительности для {len(grounded)} из {len(items)} работ…"
        )

    # Шаг 3b — остальное оцениваем ИИ (как раньше).
    hints = await _ground_norms(db, [it for it in items if it.id not in grounded])
    norms = await _ai_pick_norms(
        groups, items, hints, warnings, on_progress, skip_ids=grounded
    )

    for it in items:
        if it.id in grounded:
            continue
        norm = norms.get(it.id, {})
        # объём
        quantity = float(it.quantity) if it.quantity is not None else None
        if quantity is None:
            est_qty = norm.get("estimated_quantity")
            if isinstance(est_qty, (int, float)) and est_qty > 0:
                quantity = float(est_qty)
                it.quantity = quantity
                it.quantity_source = "ai_estimated"
                warnings.append(
                    f"Объём работы «{it.name}» оценён ИИ ({quantity:g})"
                )

        brigade = norm.get("brigade_size")
        brigade = int(brigade) if isinstance(brigade, (int, float)) and brigade else DEFAULT_BRIGADE_SIZE
        it.brigade_size = max(1, brigade)

        norm_kind = norm.get("norm_kind")
        norm_value = norm.get("norm_value")
        norm_value = float(norm_value) if isinstance(norm_value, (int, float)) and norm_value > 0 else None

        if quantity is None or norm_value is None or norm_kind not in {"norm_time", "vyrabotka"}:
            it.norm_kind = "fallback"
            it.norm_source = "ai"
            it.norm_value = None
            it.norm_unit = None
            it.duration_days = 1
            it.labor_hours = float(
                calculate_labor_hours(1, it.brigade_size, hours_per_day)
            )
            warnings.append(
                f"Для работы «{it.name}» не удалось определить норму — длительность 1 день"
            )
            continue

        it.norm_source = hints.get(it.id, {}).get("source", "ai")
        it.norm_kind = norm_kind
        it.norm_value = norm_value
        it.norm_unit = str(norm.get("norm_unit") or "").strip()[:32] or None
        it.norm_ref = str(norm.get("norm_ref") or "").strip()[:64] or hints.get(it.id, {}).get("ref")

        if norm_kind == "norm_time":
            # norm_value = чел-ч на единицу
            labor = quantity * norm_value
            duration = calculate_working_days(labor, it.brigade_size, hours_per_day) or 1
        else:
            # vyrabotka = единиц на одного рабочего в день
            duration = math.ceil(quantity / (norm_value * it.brigade_size))
            duration = max(1, duration)
            labor = calculate_labor_hours(duration, it.brigade_size, hours_per_day)

        it.duration_days = max(1, min(MAX_DURATION_DAYS, int(duration)))
        it.labor_hours = float(labor)

    # длительность группы = max по принятым работам
    for g in groups:
        g.duration_days = max(
            (it.duration_days or 1) for it in g.accepted_items
        )


async def _ground_norms(
    db: AsyncSession, items: list[KtpWbsItem]
) -> dict[str, dict]:
    """item_id -> {hint, source, ref} из ФЕР/ЕНиР по связанной позиции сметы."""
    estimate_ids = [it.estimate_id for it in items if it.estimate_id]
    if not estimate_ids:
        return {}

    estimates = {
        e.id: e
        for e in await db.scalars(
            select(Estimate).where(Estimate.id.in_(estimate_ids))
        )
    }
    hints: dict[str, dict] = {}
    for it in items:
        est = estimates.get(it.estimate_id) if it.estimate_id else None
        if not est:
            continue
        if est.fer_words_human_hours is not None:
            hints[it.id] = {
                "hint": f"ФЕР: ~{float(est.fer_words_human_hours):.3f} чел-ч/ед",
                "source": "fer",
                "ref": est.fer_words_code,
            }
            continue
        if est.enir_code:
            para = await db.scalar(
                select(EnirParagraph)
                .where(EnirParagraph.code == est.enir_code)
                .limit(1)
            )
            if para:
                norm = await db.scalar(
                    select(EnirNorm)
                    .where(EnirNorm.paragraph_id == para.id)
                    .where(EnirNorm.norm_time.isnot(None))
                    .limit(1)
                )
                if norm and norm.norm_time:
                    hints[it.id] = {
                        "hint": (
                            f"ЕНиР {para.code}: ~{float(norm.norm_time):.3f} "
                            f"чел-ч/{para.unit or 'ед'}"
                        ),
                        "source": "enir",
                        "ref": para.code,
                    }
    return hints


async def _ai_pick_norms_for_group(
    group: KtpWbsGroup,
    hints: dict[str, dict],
    warnings: list[str],
    skip_ids: set[str] | None = None,
) -> dict[str, dict]:
    skip_ids = skip_ids or set()
    pending = [it for it in group.accepted_items if it.id not in skip_ids]
    if not pending:
        return {}
    lines: list[str] = []
    for it in pending:
        qty = (
            f"{float(it.quantity):g} {it.unit or ''}".strip()
            if it.quantity is not None
            else "ОБЪЁМ НЕИЗВЕСТЕН"
        )
        hint = hints.get(it.id, {}).get("hint")
        hint_s = f" | подсказка: {hint}" if hint else ""
        lines.append(f"  [{it.id}] {it.name} | {qty}{hint_s}")
    body = "\n".join(lines)

    prompt = f"""Ты эксперт-нормировщик в строительстве. Для каждой работы в группе
«{group.title}» выбери норму производительности. НЕ СЧИТАЙ длительность — только выбери норму.

Для каждой работы верни одно из:
- "norm_kind": "norm_time", "norm_value": <чел-ч на единицу объёма>
- "norm_kind": "vyrabotka", "norm_value": <единиц объёма на 1 рабочего в день>
Также: "norm_unit" (текст, напр. "чел-ч/м3"), "brigade_size" (рекоменд. размер бригады),
"norm_ref" (код нормы если знаешь). Если объём неизвестен — оцени "estimated_quantity".

РАБОТЫ:
{body}

Верни строго JSON без markdown:
{{"items": [
  {{"id": "<id работы>", "norm_kind": "norm_time", "norm_value": 0.45,
    "norm_unit": "чел-ч/м2", "brigade_size": 3, "norm_ref": "",
    "estimated_quantity": null}}
]}}"""

    try:
        raw = await create_chat_completion(
            model=settings.KTP_GENERATION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты эксперт-нормировщик. Выбираешь нормы, но никогда не "
                        "считаешь арифметику. Возвращаешь СТРОГО валидный JSON: "
                        "без markdown, без комментариев, без trailing commas."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=settings.KTP_ESTIMATE_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_object(raw)
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI norm selection failed for group %s", group.id)
        warnings.append(
            f"ИИ не смог подобрать нормы для «{group.title}» ({exc}) — длительности по умолчанию"
        )
        return {}

    result: dict[str, dict] = {}
    for entry in parsed.get("items") or []:
        if isinstance(entry, dict) and entry.get("id"):
            result[str(entry["id"])] = entry
    return result


async def _ai_pick_norms(
    groups: list[KtpWbsGroup],
    items: list[KtpWbsItem],
    hints: dict[str, dict],
    warnings: list[str],
    on_progress: Callable[[str], Awaitable[None]] | None = None,
    skip_ids: set[str] | None = None,
) -> dict[str, dict]:
    skip_ids = skip_ids or set()
    # Только группы, где остались позиции без ФЕР-нормы.
    pending_groups = [
        g for g in groups if any(it.id not in skip_ids for it in g.accepted_items)
    ]
    if not pending_groups:
        return {}

    total = len(pending_groups)
    if on_progress:
        await on_progress(f"Оцениваем нормы для {total} групп работ…")

    tasks = [
        asyncio.create_task(_ai_pick_norms_for_group(g, hints, warnings, skip_ids))
        for g in pending_groups
    ]
    merged: dict[str, dict] = {}
    completed = 0
    for coro in asyncio.as_completed(tasks):
        result = await coro
        merged.update(result)
        completed += 1
        if on_progress:
            await on_progress(f"Оценено {completed} из {total} групп работ…")
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# ШАГ 4 — ЗАВИСИМОСТИ МЕЖДУ ГРУППАМИ
# ─────────────────────────────────────────────────────────────────────────────

async def _ai_order_groups(groups: list[KtpWbsGroup]) -> list[str]:
    """Возвращает технологически упорядоченный список group_id (линейный порядок).

    Fallback-группа («Прочие позиции сметы») в упорядочивании не участвует —
    она всегда стоит в конце списка. При сбое ИИ возвращается текущий порядок
    (по sort_order), что делает функцию безопасной для авто-вызова.
    """
    orderable = [g for g in groups if not _is_fallback_group(g.title)]
    if len(orderable) < 2:
        return [g.id for g in orderable]

    lines = "\n".join(
        f"  [{g.id}] {g.title}" + (f" (WT {g.wt_code})" if g.wt_code else "")
        for g in orderable
    )
    prompt = f"""Ты эксперт по организации строительства. Расставь ГРУППЫ работ
в правильной технологической последовательности выполнения
(подготовительные → демонтаж → земляные → фундаменты → … → отделка →
пусконаладка → благоустройство). Это линейный порядок второго уровня, НЕ
дроби группы и НЕ придумывай новые.

ГРУППЫ:
{lines}

Верни строго JSON без markdown — массив group_id в нужном порядке:
{{"order": ["<id>", "<id>", ...]}}
Включи КАЖДЫЙ id ровно один раз."""

    valid_ids = [g.id for g in orderable]
    valid_set = set(valid_ids)
    try:
        raw = await create_chat_completion(
            model=settings.KTP_GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_object(raw)
        ai_order = [str(x) for x in (parsed.get("order") or []) if str(x) in valid_set]
    except Exception:  # noqa: BLE001
        logger.exception("AI group ordering failed")
        return valid_ids

    # Дедуп с сохранением порядка + добор пропущенных в исходном порядке.
    seen: set[str] = set()
    ordered: list[str] = []
    for gid in ai_order:
        if gid not in seen:
            seen.add(gid)
            ordered.append(gid)
    for gid in valid_ids:
        if gid not in seen:
            ordered.append(gid)
            seen.add(gid)
    return ordered


async def _resolve_group_dependencies(
    groups: list[KtpWbsGroup], warnings: list[str]
) -> list[tuple[str, str]]:
    """Возвращает рёбра (group_id, depends_on_group_id) без циклов.

    Fallback-группа «прочих» работ исключается из зависимостей: у неё нет
    предшественников и от неё никто не зависит — в ГПР она стартует с самого
    начала проекта параллельно остальным.
    """
    if len(groups) < 2:
        return []

    # Variant 2.7 uses deterministic stage-instance dependencies.  AI remains
    # the fallback for all other project variants and legacy sessions.
    from app.services.ktp_floor_sequence_service import (
        build_brick_house_floor_dependencies,
        sequence_is_acyclic,
    )

    floor_report = build_brick_house_floor_dependencies(groups)
    if floor_report.applicable:
        if floor_report.unresolved_group_ids:
            warnings.append(
                "Не удалось однозначно включить в поэтажный граф группы: "
                + ", ".join(group_id[:8] for group_id in floor_report.unresolved_group_ids)
            )
        edges = list(floor_report.edges)
        if not sequence_is_acyclic(groups, edges):
            warnings.append("Поэтажная схема зависимостей содержала цикл; циклические рёбра удалены")
            return _drop_cycles(groups, edges, warnings)
        return edges

    fallback_ids = {g.id for g in groups if _is_fallback_group(g.title)}

    lines = "\n".join(
        f"  [{g.id}] {g.title}" + (f" (WT {g.wt_code})" if g.wt_code else "")
        for g in groups
    )
    prompt = f"""Ты эксперт по организации строительства. Расставь технологические
зависимости МЕЖДУ ГРУППАМИ работ. Только finish-to-start (группа начинается
после полного завершения групп-предшественников). Без лагов.

ГРУППЫ (в порядке предполагаемой последовательности):
{lines}

Верни строго JSON без markdown:
{{"dependencies": [{{"group_id": "<id>", "depends_on_group_id": "<id>"}}]}}
Указывай только реальные технологические связи. Параллельные группы не связывай."""

    valid_ids = {g.id for g in groups}
    edges: list[tuple[str, str]] = []
    try:
        raw = await create_chat_completion(
            model=settings.KTP_GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_object(raw)
        for dep in parsed.get("dependencies") or []:
            if not isinstance(dep, dict):
                continue
            gid = str(dep.get("group_id") or "")
            dep_gid = str(dep.get("depends_on_group_id") or "")
            if gid in fallback_ids or dep_gid in fallback_ids:
                continue  # «прочие» работы независимы — стартуют с начала проекта
            if gid in valid_ids and dep_gid in valid_ids and gid != dep_gid:
                edges.append((gid, dep_gid))
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI group dependency resolution failed")
        warnings.append(f"ИИ не смог расставить зависимости ({exc})")
        return []

    return _drop_cycles(groups, edges, warnings)


def _drop_cycles(
    groups: list[KtpWbsGroup],
    edges: list[tuple[str, str]],
    warnings: list[str],
) -> list[tuple[str, str]]:
    """Убирает рёбра, образующие циклы (Kahn-подобно)."""
    # adjacency: depends_on -> [dependents]
    accepted: list[tuple[str, str]] = []
    # граф предшественников для проверки достижимости
    preds: dict[str, set[str]] = {g.id: set() for g in groups}

    def reachable(start: str, target: str) -> bool:
        # есть ли путь target -> ... -> start по preds (target — предок start)
        stack = [start]
        seen = set()
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(preds.get(node, ()))
        return False

    for gid, dep_gid in edges:
        # ребро: gid зависит от dep_gid. Цикл, если dep_gid уже зависит от gid.
        if reachable(dep_gid, gid):
            warnings.append(
                "Отброшена циклическая зависимость между группами "
                f"{gid[:8]} и {dep_gid[:8]}"
            )
            continue
        preds[gid].add(dep_gid)
        accepted.append((gid, dep_gid))
    return accepted


# ─────────────────────────────────────────────────────────────────────────────
# ДАТЫ — ТОПОЛОГИЧЕСКИЙ ПРОХОД
# ─────────────────────────────────────────────────────────────────────────────

def _schedule_groups(
    groups: list[KtpWbsGroup],
    edges: list[tuple[str, str]],
    start_default: date,
) -> None:
    by_id = {g.id: g for g in groups}
    deps: dict[str, list[str]] = {g.id: [] for g in groups}
    for gid, dep_gid in edges:
        deps[gid].append(dep_gid)

    scheduled: dict[str, date] = {}

    def resolve(gid: str, stack: set[str]) -> date:
        if gid in scheduled:
            return scheduled[gid]
        if gid in stack:  # защита (циклы уже убраны, но на всякий случай)
            scheduled[gid] = start_default
            return start_default
        stack.add(gid)
        g = by_id[gid]
        if not deps[gid]:
            start = start_default
        else:
            # старт = max по предшественникам (конец+1 + техпауза подтипа)
            start = max(
                next_task_start_date(
                    resolve(dep_gid, stack), by_id[dep_gid].duration_days or 1
                )
                + timedelta(days=int(getattr(by_id[dep_gid], "prod_lag_after", 0) or 0))
                for dep_gid in deps[gid]
            )
        stack.discard(gid)
        g.start_date = start
        scheduled[gid] = start
        return start

    for g in groups:
        resolve(g.id, set())


# ─────────────────────────────────────────────────────────────────────────────
# ЗАПИСЬ В GANTT
# ─────────────────────────────────────────────────────────────────────────────

async def _write_gantt(
    db: AsyncSession,
    session: KtpEstimateSession,
    batch: EstimateBatch,
    groups: list[KtpWbsGroup],
    dep_edges: list[tuple[str, str]],
) -> dict[str, int]:
    from app.services.upload_service import _get_row_order_offset

    project_id = session.project_id
    batch_id = batch.id

    # soft-delete существующих задач батча + их зависимостей
    existing_ids = list(
        await db.scalars(
            select(GanttTask.id)
            .where(GanttTask.project_id == project_id)
            .where(GanttTask.estimate_batch_id == batch_id)
            .where(GanttTask.deleted_at.is_(None))
        )
    )
    if existing_ids:
        await db.execute(
            delete(TaskDependency).where(
                or_(
                    TaskDependency.task_id.in_(existing_ids),
                    TaskDependency.depends_on.in_(existing_ids),
                )
            )
        )
        await db.execute(
            GanttTask.__table__.update()
            .where(GanttTask.id.in_(existing_ids))
            .values(deleted_at=datetime.now(timezone.utc))
        )
        await db.flush()

    hours_per_day = float(batch.hours_per_day or DEFAULT_HOURS_PER_DAY)
    row_order = await _get_row_order_offset(project_id, db)
    start_default = batch.start_date or date.today()

    def _copy_stage_metadata(target, source) -> None:
        for field in (
            "stage_instance_id", "template_stage_number", "stage_number",
            "canonical_stage_id", "floor_number", "floor_kind", "floor_label",
            "floor_component", "component_role", "source_row_key", "projection_id",
            "operation_code", "operation_package_code", "semantic_stage_option_id",
            "stage_option_source", "work_scope_key", "applicability_hash",
            "applicability_hash_version", "applicability_schema_version",
        ):
            value = getattr(source, field, None)
            if value is not None:
                try:
                    setattr(target, field, value)
                except Exception:  # noqa: BLE001 - optional ORM extension fields
                    logger.debug("Cannot copy Gantt metadata %s", field)

    # корневая задача батча
    max_end = max(
        task_end_date(g.start_date or start_default, g.duration_days or 1)
        for g in groups
    )
    root_days = max(1, (max_end - start_default).days + 1)
    root = GanttTask(
        id=_uuid(),
        project_id=project_id,
        estimate_batch_id=batch_id,
        name=batch.name,
        start_date=start_default,
        working_days=root_days,
        hours_per_day=hours_per_day,
        progress=0,
        is_group=True,
        type="project",
        color="#0f172a",
        row_order=row_order,
    )
    db.add(root)
    row_order += 1.0

    tasks = 1
    group_task_id: dict[str, str] = {}
    leaf_task_ids_by_group: dict[str, list[str]] = {}
    for g in groups:
        g_task = GanttTask(
            id=_uuid(),
            project_id=project_id,
            estimate_batch_id=batch_id,
            parent_id=root.id,
            name=g.title,
            start_date=g.start_date or start_default,
            working_days=g.duration_days or 1,
            hours_per_day=hours_per_day,
            progress=0,
            is_group=True,
            type="project",
            row_order=row_order,
        )
        _copy_stage_metadata(g_task, g)
        db.add(g_task)
        g.gantt_task_id = g_task.id
        group_task_id[g.id] = g_task.id
        row_order += 1.0
        tasks += 1

        for it in sorted(g.accepted_items, key=lambda x: float(x.sort_order)):
            i_task = GanttTask(
                id=_uuid(),
                project_id=project_id,
                estimate_batch_id=batch_id,
                estimate_id=it.estimate_id,
                parent_id=g_task.id,
                name=it.name,
                start_date=g.start_date or start_default,
                working_days=it.duration_days or 1,
                workers_count=it.brigade_size,
                labor_hours=it.labor_hours,
                hours_per_day=hours_per_day,
                progress=0,
                is_group=False,
                type="task",
                row_order=row_order,
            )
            _copy_stage_metadata(i_task, it)
            db.add(i_task)
            it.gantt_task_id = i_task.id
            leaf_task_ids_by_group.setdefault(g.id, []).append(i_task.id)
            row_order += 1.0
            tasks += 1

    await db.flush()

    # зависимости между ГРУППОВЫМИ задачами (с техпаузой подтипа-предшественника)
    group_by_id = {g.id: g for g in groups}
    deps = 0
    for gid, dep_gid in dep_edges:
        t1 = group_task_id.get(gid)
        t2 = group_task_id.get(dep_gid)
        if t1 and t2:
            lag = int(getattr(group_by_id.get(dep_gid), "prod_lag_after", 0) or 0)
            db.add(TaskDependency(task_id=t1, depends_on=t2, lag_days=lag))
            deps += 1

    # Synthetic milestone joins the last-floor partitions branch and the roof
    # branch. It is deliberately not used as an automatic predecessor for the
    # facade contour (2.7.13/2.7.15/2.7.16).
    from app.services.ktp_floor_sequence_service import (
        STRUCTURAL_COMPLETION_STAGE_INSTANCE_ID,
        build_brick_house_floor_dependencies,
    )

    floor_report = build_brick_house_floor_dependencies(groups)
    milestone = floor_report.milestone
    if milestone is not None:
        wait_leaf_ids: list[str] = []
        for group_id in milestone.wait_group_ids:
            leaf_ids = leaf_task_ids_by_group.get(group_id) or []
            if leaf_ids:
                wait_leaf_ids.append(leaf_ids[-1])
            elif group_task_id.get(group_id):
                wait_leaf_ids.append(group_task_id[group_id])
        if wait_leaf_ids:
            wait_groups = [group_by_id[group_id] for group_id in milestone.wait_group_ids if group_id in group_by_id]
            milestone_start = max(
                task_end_date(group.start_date or start_default, group.duration_days or 1)
                for group in wait_groups
            ) if wait_groups else start_default
            milestone_task = GanttTask(
                id=_uuid(),
                project_id=project_id,
                estimate_batch_id=batch_id,
                parent_id=root.id,
                name="Завершение конструктивного блока",
                start_date=milestone_start,
                working_days=0,
                hours_per_day=hours_per_day,
                progress=0,
                is_group=False,
                type="task",
                row_order=row_order,
            )
            setattr(milestone_task, "task_kind", "milestone")
            setattr(milestone_task, "stage_instance_id", STRUCTURAL_COMPLETION_STAGE_INSTANCE_ID)
            db.add(milestone_task)
            row_order += 1.0
            tasks += 1
            await db.flush()
            for wait_task_id in wait_leaf_ids:
                db.add(TaskDependency(task_id=milestone_task.id, depends_on=wait_task_id, lag_days=0))
                deps += 1

    batch.start_date = start_default
    await db.flush()
    return {"tasks": tasks, "deps": deps}
