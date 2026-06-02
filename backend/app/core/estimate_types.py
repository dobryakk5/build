"""Single source of truth for estimate line item types.

Historically the codebase only recognised ``work`` and ``mechanism`` and the
resolution helper defaulted *anything* else back to ``work`` — which meant a
``material`` or ``overhead`` row would silently leak into the Gantt/KTP build.

This module defines the full vocabulary and a single ``resolve_item_type``
helper so the rule lives in one place instead of being duplicated (and drifting)
across the model, upload service, KTP services and the estimates router.
"""
from __future__ import annotations

from typing import Any

ESTIMATE_ITEM_TYPE_WORK = "work"          # работа — попадает в Гант и КТП
ESTIMATE_ITEM_TYPE_MATERIAL = "material"  # материал — не попадает в Гант
ESTIMATE_ITEM_TYPE_MECHANISM = "mechanism"  # техника/механизм
ESTIMATE_ITEM_TYPE_OVERHEAD = "overhead"  # транспортные, накладные, ИТР, проценты
ESTIMATE_ITEM_TYPE_UNKNOWN = "unknown"    # сомнительная строка для ручной проверки

VALID_ESTIMATE_ITEM_TYPES = {
    ESTIMATE_ITEM_TYPE_WORK,
    ESTIMATE_ITEM_TYPE_MATERIAL,
    ESTIMATE_ITEM_TYPE_MECHANISM,
    ESTIMATE_ITEM_TYPE_OVERHEAD,
    ESTIMATE_ITEM_TYPE_UNKNOWN,
}

# Rows imported before classification existed have no ``item_type`` — they are
# legacy work rows, so an unrecognised value falls back to ``work``.
DEFAULT_ESTIMATE_ITEM_TYPE = ESTIMATE_ITEM_TYPE_WORK


def normalize_item_type(value: Any) -> str:
    """Return ``value`` if it is a recognised type, else the default (``work``)."""
    return value if value in VALID_ESTIMATE_ITEM_TYPES else DEFAULT_ESTIMATE_ITEM_TYPE


def resolve_item_type(estimate: Any) -> str:
    """Resolve an estimate's item type, trusting the stored value across the full
    vocabulary.

    Works both with real ``Estimate`` ORM objects (which expose an ``item_type``
    property) and with lightweight stubs that only carry ``raw_data``. Anything
    unrecognised falls back to ``work`` for backward compatibility.
    """
    item_type = getattr(estimate, "item_type", None)
    if item_type in VALID_ESTIMATE_ITEM_TYPES:
        return item_type

    raw_data = getattr(estimate, "raw_data", None)
    if isinstance(raw_data, dict):
        stored = raw_data.get("item_type")
        if stored in VALID_ESTIMATE_ITEM_TYPES:
            return stored

    return DEFAULT_ESTIMATE_ITEM_TYPE
