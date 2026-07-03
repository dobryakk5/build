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
    """Return whole working days for a valid positive labour/capacity tuple.

    Missing workers are not silently treated as one worker: duration cannot be
    derived until both labour and daily crew capacity are known. Rounding to a
    whole shift belongs here, not in labour-hour calculation.
    """
    if labor_hours is None or workers_count is None or hours_per_day is None:
        return None
    try:
        labor = float(labor_hours)
        workers = int(workers_count)
        norm = float(hours_per_day)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(labor)
        or not math.isfinite(norm)
        or labor <= 0
        or workers <= 0
        or norm <= 0
    ):
        return None
    return math.ceil(labor / (workers * norm))


def calculate_labor_hours(
    working_days: int,
    workers_count: int | None,
    hours_per_day: float | None = DEFAULT_HOURS_PER_DAY,
) -> float:
    workers = max(1, int(workers_count or 1))
    norm = normalize_hours_per_day(hours_per_day)
    return round(float(working_days) * workers * norm, 2)
