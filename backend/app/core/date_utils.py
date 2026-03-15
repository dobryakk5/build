# backend/app/core/date_utils.py
"""
Единственное место где считаются рабочие дни.
Используется и в бэке, и логика дублируется на фронте.

Правило: рабочие дни = пн–пт минус праздники из таблицы holidays.
Calendar days нигде не используются для расчёта длительности задач.
"""
from datetime import date, timedelta
from functools import lru_cache


def add_working_days(
    start: date,
    working_days: int,
    holidays: set[date] | None = None,
) -> date:
    """
    Прибавляет рабочие дни к дате.
    start=2026-03-13 (пт), working_days=1 → 2026-03-16 (пн)
    """
    if working_days <= 0:
        return start
    if holidays is None:
        holidays = set()

    current = start
    added = 0
    while added < working_days:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holidays:  # пн=0 … пт=4
            added += 1
    return current


def working_days_between(
    start: date,
    end: date,
    holidays: set[date] | None = None,
) -> int:
    """
    Считает рабочие дни между двумя датами (не включая start, включая end).
    """
    if holidays is None:
        holidays = set()
    if end <= start:
        return 0

    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holidays:
            count += 1
    return count


def task_end_date(start: date, working_days: int, holidays: set[date] | None = None) -> date:
    """Дата окончания задачи (включительно)."""
    return add_working_days(start, working_days, holidays)
