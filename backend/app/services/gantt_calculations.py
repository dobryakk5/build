from __future__ import annotations

import math


DEFAULT_HOURS_PER_DAY = 8.0


def normalize_hours_per_day(hours_per_day: float | None) -> float:
    value = float(hours_per_day or DEFAULT_HOURS_PER_DAY)
    return max(0.01, value)


def calculate_working_days(
    labor_hours: float | None,
    workers_count: int | None,
    hours_per_day: float | None = DEFAULT_HOURS_PER_DAY,
) -> int | None:
    if labor_hours is None:
        return None

    workers = max(1, int(workers_count or 1))
    norm = normalize_hours_per_day(hours_per_day)
    return max(1, math.ceil(float(labor_hours) / (workers * norm)))


def calculate_labor_hours(
    working_days: int,
    workers_count: int | None,
    hours_per_day: float | None = DEFAULT_HOURS_PER_DAY,
) -> float:
    workers = max(1, int(workers_count or 1))
    norm = normalize_hours_per_day(hours_per_day)
    return round(float(working_days) * workers * norm, 2)
