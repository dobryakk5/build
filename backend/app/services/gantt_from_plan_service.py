"""
Шаг 5: расчёт длительности и сборка Ганта из плана работ.

Алгоритм:
  1. compute_durations(batch_id):
     для каждой карточки plan с fer_table_id:
        avg_h_per_100 = AVG(fer_rows.h_hour) WHERE table_id = card.fer_table_id
        h_per_unit    = avg_h_per_100 / 100              ← ФЕР хранит часы/100ед
        labor_hours   = h_per_unit * card.quantity
        duration_days = ceil(labor_hours / (workers * hours_per_day))
     UPDATE card SET human_hours_per_unit, duration_days

  2. build_gantt(batch_id, start_date, hours_per_day):
     Группировка карточек по (work_type, stage) → одна задача Ганта на группу
     Имя задачи: «<wt_name> — <stage_name>»
     workers_count = max по карточкам группы
     labor_hours   = sum по группе
     duration      = ceil(labor / (workers * hpd))

  3. Зависимости — по порядку stage_code (ST-01..ST-12):
     Все задачи stage_(n+1) → depends_on все задачи stage_n
     В рамках одного stage задачи параллельны (нет зависимостей)
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.gantt_calculations import (
    DEFAULT_HOURS_PER_DAY,
    calculate_working_days,
    normalize_hours_per_day,
)

logger = logging.getLogger(__name__)

DEFAULT_WORKERS_PER_TASK = 4
# Дефолт длительности для карточки без FER — чтобы попасть в Гант хотя бы как заглушка
FALLBACK_DURATION_DAYS = 1

# Парсим из clarification «делитель» — например "— 100 м3" → 100, "— 1000 шт" → 1000
_DIVISOR_RE = re.compile(r"—\s*(\d+(?:[.,]\d+)?)\s*\S+\s*$")


def parse_fer_row_divisor(clarification: str | None, default: float = 1.0) -> float:
    """
    Из строки fer_rows.clarification извлекает множитель (н-р «100 м3» → 100).
    Если в конце нет «— N <unit>», возвращает default (для ФЕР без множителя).
    """
    if not clarification:
        return default
    m = _DIVISOR_RE.search(clarification)
    if not m:
        return default
    try:
        return float(m.group(1).replace(",", "."))
    except (ValueError, TypeError):
        return default

# Порядок стадий (для авто-зависимостей и сортировки)
STAGE_ORDER = [
    "ST-01", "ST-02", "ST-03", "ST-04", "ST-05",
    "ST-06", "ST-07", "ST-08", "ST-09", "ST-10",
    "ST-11", "ST-12",
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Расчёт длительности карточек
# ─────────────────────────────────────────────────────────────────────────────

async def compute_card_duration(
    db: AsyncSession,
    plan_id: int,
    workers_count: int | None = None,
    hours_per_day: float | None = None,
) -> dict[str, Any]:
    """Посчитать h_per_unit и duration_days для одной карточки."""
    card = (await db.execute(
        text(
            """
            SELECT p.id, p.fer_table_id, p.fer_row_id, p.quantity, p.workers_count, p.unit,
                   eb.workers_count AS batch_workers,
                   eb.hours_per_day AS batch_hpd
            FROM fer.project_work_plan p
            JOIN estimate_batches eb ON eb.id = p.estimate_batch_id
            WHERE p.id = :id
            """
        ),
        {"id": plan_id},
    )).mappings().first()
    if not card:
        raise ValueError(f"plan card {plan_id} not found")

    if not card["fer_table_id"]:
        return {"plan_id": plan_id, "skipped": "no fer_table_id"}
    if card["quantity"] is None:
        return {"plan_id": plan_id, "skipped": "no quantity"}

    # Если выбрана конкретная строка — берём её h_hour и парсим divisor из clarification.
    # Иначе fallback — AVG по всем строкам с дефолтным divisor=100.
    h_hour: float | None = None
    divisor: float = 100.0
    source: str = "avg"
    if card["fer_row_id"]:
        row = (await db.execute(
            text("SELECT h_hour, clarification FROM fer.fer_rows WHERE id = :id"),
            {"id": card["fer_row_id"]},
        )).mappings().first()
        if row and row["h_hour"] is not None:
            h_hour = float(row["h_hour"])
            divisor = parse_fer_row_divisor(row["clarification"], default=1.0)
            source = "row"

    if h_hour is None:
        avg = (await db.execute(
            text(
                """
                SELECT AVG(h_hour) FROM fer.fer_rows
                WHERE table_id = :tid AND h_hour IS NOT NULL
                """
            ),
            {"tid": card["fer_table_id"]},
        )).scalar()
        if not avg:
            return {"plan_id": plan_id, "skipped": "no fer_rows hours"}
        h_hour = float(avg)
        divisor = 100.0  # для AVG используем стандартный множитель

    h_per_unit = h_hour / divisor
    labor_hours = h_per_unit * float(card["quantity"])

    workers = workers_count or card["workers_count"] or card["batch_workers"] or DEFAULT_WORKERS_PER_TASK
    hpd     = hours_per_day or float(card["batch_hpd"] or DEFAULT_HOURS_PER_DAY)
    days    = max(1, math.ceil(labor_hours / (workers * hpd)))

    await db.execute(
        text(
            """
            UPDATE fer.project_work_plan
            SET human_hours_per_unit = :hpu,
                workers_count        = COALESCE(workers_count, :w),
                duration_days        = :d,
                updated_at           = NOW()
            WHERE id = :id
            """
        ),
        {"hpu": h_per_unit, "w": workers, "d": days, "id": plan_id},
    )
    return {
        "plan_id": plan_id, "h_per_unit": h_per_unit,
        "labor_hours": round(labor_hours, 2), "workers": workers,
        "duration_days": days, "source": source,
        "h_hour_raw": h_hour, "divisor": divisor,
    }


async def compute_all_durations(
    db: AsyncSession,
    estimate_batch_id: str,
) -> dict[str, Any]:
    """Расчёт длительности для всех карточек батча с FER + объёмом."""
    rows = (await db.execute(
        text(
            """
            SELECT id FROM fer.project_work_plan
            WHERE estimate_batch_id = :b
              AND parent_id IS NULL
              AND fer_table_id IS NOT NULL
              AND quantity IS NOT NULL
              AND status NOT IN ('removed')
            """
        ),
        {"b": estimate_batch_id},
    )).mappings().all()

    computed = 0
    skipped = 0
    for r in rows:
        try:
            res = await compute_card_duration(db, r["id"])
            if res.get("skipped"):
                skipped += 1
            else:
                computed += 1
        except Exception as e:
            logger.warning("compute failed for %s: %s", r["id"], e)
            skipped += 1

    await db.commit()
    return {"total": len(rows), "computed": computed, "skipped": skipped}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Сборка задач Ганта
# ─────────────────────────────────────────────────────────────────────────────

def _stage_idx(stage_code: str | None) -> int:
    if not stage_code:
        return 99
    try:
        return STAGE_ORDER.index(stage_code)
    except ValueError:
        return 99


def _next_workday(d: date) -> date:
    """Следующий рабочий день (Mon-Fri). Пропускаем праздники не учитываем тут — это упрощение."""
    while d.weekday() >= 5:
        d = d + timedelta(days=1)
    return d


def _add_working_days(start: date, days: int) -> date:
    """Прибавляет N рабочих дней к дате старта (Mon-Fri)."""
    d = start
    added = 0
    while added < days:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


async def build_gantt(
    db: AsyncSession,
    estimate_batch_id: str,
    start_date: date,
    hours_per_day: float | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """
    Собрать задачи Ганта из плана работ.

    Группировка: одна задача = (work_type_code, stage_code) внутри батча.
    Зависимости: stage_(n+1) → stage_n (все задачи следующего stage зависят от всех задач предыдущего).
    Даты: каскадом от start_date по зависимостям.
    """
    # 0. Получаем project_id и hours_per_day из batch'а
    batch = (await db.execute(
        text(
            "SELECT project_id, COALESCE(hours_per_day, 8.0) AS hpd FROM estimate_batches WHERE id = :b"
        ),
        {"b": estimate_batch_id},
    )).mappings().first()
    if not batch:
        raise ValueError(f"batch {estimate_batch_id} not found")

    project_id = batch["project_id"]
    hpd = float(hours_per_day or batch["hpd"])

    # 1. Очистка старых задач (если replace)
    if replace:
        await db.execute(
            text("DELETE FROM gantt_tasks WHERE estimate_batch_id = :b"),
            {"b": estimate_batch_id},
        )

    # 1.5. Автокомпьют длительностей для карточек с FER+quantity (чтобы юзеру не делать вручную)
    try:
        await compute_all_durations(db, estimate_batch_id)
    except Exception as e:
        logger.warning("compute_all_durations during build failed: %s", e)

    # 2. Все карточки в Гант — БЕЗ группировки.
    #    Берём все верхнеуровневые карточки (parent_id IS NULL), кроме removed.
    #    Если нет duration_days — назначаем FALLBACK_DURATION_DAYS.
    cards = (await db.execute(
        text(
            """
            SELECT
              p.id,
              p.source_label, p.source_section, p.nw_item_code,
              i.unique_label AS nw_label,
              i.work_type_code,
              COALESCE(p.stage_code, (i.stage_codes)[1]) AS stage_code,
              p.duration_days,
              COALESCE(p.workers_count, :default_workers) AS workers_count,
              p.human_hours_per_unit, p.quantity, p.fer_table_id
            FROM fer.project_work_plan p
            JOIN fer.nw_item i ON i.code = p.nw_item_code
            WHERE p.estimate_batch_id = :b
              AND p.parent_id IS NULL
              AND p.status NOT IN ('removed')
            ORDER BY p.id
            """
        ),
        {"b": estimate_batch_id, "default_workers": DEFAULT_WORKERS_PER_TASK},
    )).mappings().all()

    # Нормализация: если нет duration_days — дефолт
    fallback_used = 0
    cards_normalized: list[dict] = []
    for c in cards:
        c = dict(c)
        if c["duration_days"] is None:
            c["duration_days"] = FALLBACK_DURATION_DAYS
            fallback_used += 1
        cards_normalized.append(c)
    cards = cards_normalized

    def labor_for(c) -> float:
        if c["human_hours_per_unit"] is not None and c["quantity"] is not None:
            return float(c["human_hours_per_unit"]) * float(c["quantity"])
        if c["duration_days"] is not None:
            return float(c["duration_days"]) * float(c["workers_count"] or DEFAULT_WORKERS_PER_TASK) * hpd
        return 0.0

    if not cards:
        # Поможем понять причину
        diag = (await db.execute(
            text(
                """
                SELECT
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE parent_id IS NULL) AS top_level,
                  COUNT(*) FILTER (WHERE parent_id IS NULL AND quantity IS NOT NULL) AS with_qty,
                  COUNT(*) FILTER (WHERE parent_id IS NULL AND status = 'removed') AS removed
                FROM fer.project_work_plan WHERE estimate_batch_id = :b
                """
            ),
            {"b": estimate_batch_id},
        )).mappings().first()
        return {
            "created": 0, "deps": 0, "stages": 0,
            "warning": (
                f"Нет карточек с объёмом для построения. "
                f"Всего карточек: {diag['total']}, верхнего уровня: {diag['top_level']}, "
                f"с объёмом (quantity): {diag['with_qty']}, удалено: {diag['removed']}. "
                f"Заполните объём (quantity) хотя бы у части карточек."
            ),
        }

    # 3. Группировка только для каскадирования дат по этапам (НЕ для слияния задач).
    #    Каждая карточка = отдельная задача Ганта. В одном этапе задачи стартуют параллельно,
    #    следующий этап начинается после окончания всех задач предыдущего этапа.
    cards_by_stage: dict[str | None, list[dict]] = {}
    for c in cards:
        cards_by_stage.setdefault(c["stage_code"], []).append(c)

    # Для имени NW (на случай отсутствия source_label)
    sorted_stages = sorted(cards_by_stage.keys(), key=_stage_idx)

    # stage_end_date[stage_code] = max окончание задач этапа
    stage_end_date: dict[str | None, date] = {}
    tasks_by_stage: dict[str | None, list[str]] = {}
    created_task_ids: list[str] = []

    for stage_code in sorted_stages:
        # Старт этапа = max(end_dates) предыдущих этапов или start_date
        prev_idx = _stage_idx(stage_code) - 1
        prev_end = None
        for i in range(prev_idx, -1, -1):
            sc = STAGE_ORDER[i] if 0 <= i < len(STAGE_ORDER) else None
            if sc in stage_end_date:
                prev_end = stage_end_date[sc]
                break
        stage_start = (prev_end + timedelta(days=1)) if prev_end else start_date
        stage_start = _next_workday(stage_start)

        max_end_in_stage = stage_start
        task_ids_here: list[str] = []

        for c in cards_by_stage[stage_code]:
            # Имя задачи: исходное из сметы, fallback — название NW
            raw_name = (c["source_label"] or c["nw_label"] or c["nw_item_code"]).strip()
            task_name = raw_name[:255]

            duration = max(1, int(c["duration_days"]))
            workers  = int(c["workers_count"] or DEFAULT_WORKERS_PER_TASK)
            labor    = labor_for(c)

            task_id = str(uuid.uuid4())
            await db.execute(
                text(
                    """
                    INSERT INTO gantt_tasks
                      (id, project_id, estimate_batch_id, name, start_date,
                       working_days, workers_count, labor_hours, hours_per_day,
                       progress, type, color)
                    VALUES
                      (:id, :pid, :bid, :name, :start,
                       :days, :workers, :hours, :hpd,
                       0, 'task', NULL)
                    """
                ),
                {
                    "id": task_id, "pid": project_id, "bid": estimate_batch_id,
                    "name": task_name, "start": stage_start,
                    "days": duration, "workers": workers,
                    "hours": round(labor, 2) if labor else None, "hpd": hpd,
                },
            )

            task_end = _add_working_days(stage_start, duration - 1)
            if task_end > max_end_in_stage:
                max_end_in_stage = task_end

            task_ids_here.append(task_id)
            created_task_ids.append(task_id)

        stage_end_date[stage_code] = max_end_in_stage
        tasks_by_stage[stage_code] = task_ids_here

    # 4. Зависимости: каждая задача след. этапа depends_on каждой задачи предыдущего этапа
    deps_created = 0
    sorted_stages_filled = [s for s in sorted_stages if s in tasks_by_stage and tasks_by_stage[s]]
    for i in range(1, len(sorted_stages_filled)):
        cur_stage  = sorted_stages_filled[i]
        prev_stage = sorted_stages_filled[i - 1]
        for cur_id in tasks_by_stage[cur_stage]:
            for prev_id in tasks_by_stage[prev_stage]:
                await db.execute(
                    text(
                        """
                        INSERT INTO task_dependencies (task_id, depends_on)
                        VALUES (:t, :d)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"t": cur_id, "d": prev_id},
                )
                deps_created += 1

    # 7. Помечаем карточки plan как scheduled
    await db.execute(
        text(
            """
            UPDATE fer.project_work_plan
            SET status = 'scheduled', updated_at = NOW()
            WHERE estimate_batch_id = :b
              AND parent_id IS NULL
              AND duration_days IS NOT NULL
              AND status IN ('confirmed', 'fer_mapped', 'auto_proposed', 'custom_added')
            """
        ),
        {"b": estimate_batch_id},
    )

    await db.commit()
    return {
        "created":          len(created_task_ids),
        "deps":             deps_created,
        "stages":           len(sorted_stages_filled),
        "fallback_used":    fallback_used,
        "fallback_note":    (
            f"{fallback_used} карточек без расчёта длительности — назначен дефолт "
            f"{FALLBACK_DURATION_DAYS} дн. Уточните вручную через 🔗/📋."
        ) if fallback_used else None,
        "task_ids":         created_task_ids[:5],
    }
