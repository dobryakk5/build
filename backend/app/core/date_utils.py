# backend/app/core/date_utils.py
"""
Единственное место, где считаются календарные даты задач.

Правило:
- duration = календарные дни
- dur=1 -> старт и финиш в один день
- следующая зависимая задача стартует на следующий календарный день

Параметр holidays сохранён в сигнатурах для совместимости вызовов, но не используется.
"""
from datetime import date, timedelta


def add_working_days(
    start: date,
    working_days: int,
    holidays: set[date] | None = None,
) -> date:
    """
    Историческое имя: фактически прибавляет календарные дни к дате.
    start=2026-03-13, working_days=1 -> 2026-03-14
    """
    return start + timedelta(days=max(0, working_days))


def working_days_between(
    start: date,
    end: date,
    holidays: set[date] | None = None,
) -> int:
    """
    Историческое имя: фактически считает календарные дни между двумя датами
    (не включая start, включая end).
    """
    return max(0, (end - start).days)


def task_end_date(start: date, working_days: int, holidays: set[date] | None = None) -> date:
    """Дата окончания задачи (включительно)."""
    return start + timedelta(days=max(0, working_days - 1))


def next_task_start_date(start: date, working_days: int, holidays: set[date] | None = None) -> date:
    """Дата старта следующей зависимой задачи после текущей."""
    return add_working_days(start, max(1, working_days), holidays)
