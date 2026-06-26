"""UTC-aware time helpers shared by ORM models and services."""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return an aware UTC datetime suitable for TIMESTAMP(timezone=True)."""
    return datetime.now(timezone.utc)
