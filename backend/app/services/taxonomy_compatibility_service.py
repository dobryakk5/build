"""Compatibility helpers for persisted estimate taxonomy assignments.

The runtime taxonomy is mutable between releases, while imported estimates are
historical records.  This module snapshots the assignment made at import time
and prevents an old batch from being silently resolved through a newer JSON
structure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Iterable

BRICK_HOUSE_VARIANT_ID = "residential_construction_kirpichnye_doma"
BRICK_HOUSE_VARIANT_NUMBER = "2.7"
BRICK_HOUSE_VARIANT_SCHEMA_VERSION = "brick_house_2_7@2.0.0"
SNAPSHOT_SCHEMA_VERSION = "taxonomy_snapshot@1.0.0"
_SUPPORTED_V65_SNAPSHOT_RE = re.compile(
    r"^construction_work_dictionary_v6_5_\d+@"
)

SNAPSHOT_KEYS = (
    "estimate_type_id",
    "estimate_type_number",
    "project_variant_id",
    "project_variant_number",
    "canonical_stage_id",
    "stage_instance_id",
    "template_stage_number",
    "work_stage_number",
    "work_stage_title",
    "floor_number",
    "floor_kind",
    "floor_label",
    "floor_component",
    "component_role",
    "stage_options_mode",
    "stage_option_id",
    "semantic_stage_option_id",
    "stage_option_title",
    "section_id",
    "subtype_id",
    "work_section_code",
    "work_subtype_code",
    "work_subtype_name",
    "operation_code",
    "operation_package_code",
    "work_scope_key",
    "dictionary_version",
    "prompt_version",
)


class LegacyTaxonomyLockedError(ValueError):
    """Raised when a caller tries to reclassify a historical assignment."""

    code = "legacy_taxonomy_locked"


@dataclass(frozen=True)
class PersistedStageDescriptor:
    number: str
    title: str
    canonical_stage_id: str | None
    stage_instance_id: str | None
    template_stage_number: str | None
    sort_order: float
    floor_number: int | None = None
    floor_kind: str | None = None
    floor_label: str | None = None
    floor_component: str | None = None
    component_role: str | None = None
    stage_options_mode: str = "none"

    def as_stage(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "canonical_stage_id": self.canonical_stage_id,
            "stage_instance_id": self.stage_instance_id,
            "template_stage_number": self.template_stage_number,
            "sort_order": self.sort_order,
            "floor_number": self.floor_number,
            "floor_kind": self.floor_kind,
            "floor_label": self.floor_label,
            "floor_component": self.floor_component,
            "component_role": self.component_role,
            "stage_options_mode": self.stage_options_mode,
            "taxonomy_source": "persisted_snapshot",
        }


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _raw(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        raw = record.get("raw_data")
        return raw if isinstance(raw, dict) else record
    raw = getattr(record, "raw_data", None)
    return raw if isinstance(raw, dict) else {}


def _value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        direct = record.get(key)
    else:
        direct = getattr(record, key, None)
    if direct not in (None, ""):
        return direct
    raw = _raw(record)
    snapshot = raw.get("taxonomy_snapshot")
    if isinstance(snapshot, dict) and snapshot.get(key) not in (None, ""):
        return snapshot.get(key)
    return raw.get(key)


def current_dictionary_version() -> str:
    from app.services.work_taxonomy_service import dictionary_version

    return dictionary_version()


def variant_schema_version(project_variant_id: Any, project_variant_number: Any = None) -> str | None:
    variant_id = _clean(project_variant_id)
    variant_number = _clean(project_variant_number)
    if variant_id == BRICK_HOUSE_VARIANT_ID or variant_number == BRICK_HOUSE_VARIANT_NUMBER:
        return BRICK_HOUSE_VARIANT_SCHEMA_VERSION
    return None


def build_taxonomy_snapshot(
    raw: dict[str, Any],
    *,
    hierarchy_selection: dict[str, Any] | None = None,
    building_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hierarchy_selection = hierarchy_selection or {}
    snapshot: dict[str, Any] = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    for key in SNAPSHOT_KEYS:
        value = raw.get(key)
        if value in (None, ""):
            value = hierarchy_selection.get(key)
        if value not in (None, ""):
            snapshot[key] = value

    dictionary = (
        raw.get("dictionary_version")
        or hierarchy_selection.get("taxonomy_dictionary_version")
        or current_dictionary_version()
    )
    snapshot["dictionary_version"] = str(dictionary)
    project_variant_id = snapshot.get("project_variant_id") or hierarchy_selection.get("project_variant_id")
    project_variant_number = snapshot.get("project_variant_number") or hierarchy_selection.get("project_variant_number")
    schema_version = variant_schema_version(project_variant_id, project_variant_number)
    if schema_version:
        snapshot["variant_schema_version"] = schema_version
    snapshot["building_params"] = dict(building_params or {})
    return snapshot


def ensure_taxonomy_snapshot(
    raw: dict[str, Any],
    *,
    hierarchy_selection: dict[str, Any] | None = None,
    building_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = raw.get("taxonomy_snapshot")
    if not isinstance(existing, dict) or not existing.get("snapshot_schema_version"):
        existing = build_taxonomy_snapshot(
            raw,
            hierarchy_selection=hierarchy_selection,
            building_params=building_params,
        )
        raw["taxonomy_snapshot"] = existing
    raw.setdefault("dictionary_version", existing.get("dictionary_version"))
    if existing.get("variant_schema_version"):
        raw.setdefault("variant_schema_version", existing.get("variant_schema_version"))
    raw["taxonomy_locked"] = True
    raw["taxonomy_resolution_mode"] = "persisted_snapshot"
    return raw


def stored_dictionary_version(record: Any) -> str | None:
    return _clean(_value(record, "dictionary_version") or _value(record, "taxonomy_dictionary_version"))


def is_legacy_taxonomy_record(record: Any, *, current_version: str | None = None) -> bool:
    raw = _raw(record)
    explicit = raw.get("taxonomy_legacy")
    if explicit is not None:
        return bool(explicit)

    current = current_version or current_dictionary_version()
    stored = stored_dictionary_version(record)
    if stored and stored != current:
        return True

    variant_id = _clean(_value(record, "project_variant_id"))
    variant_number = _clean(_value(record, "project_variant_number"))
    is_brick = variant_id == BRICK_HOUSE_VARIANT_ID or variant_number == BRICK_HOUSE_VARIANT_NUMBER
    if not is_brick:
        return False

    # Old 2.7 batches did not have dynamic stage instances/building params.  A
    # missing version on such a record must be treated conservatively.
    stage_number = _clean(_value(record, "work_stage_number"))
    stage_instance_id = _clean(_value(record, "stage_instance_id"))
    snapshot = raw.get("taxonomy_snapshot") if isinstance(raw.get("taxonomy_snapshot"), dict) else {}
    building_params = snapshot.get("building_params") or raw.get("building_params")
    if stage_number and not stage_instance_id and not building_params:
        return True
    return False


def batch_uses_legacy_taxonomy(batch: Any, estimates: Iterable[Any]) -> bool:
    current = current_dictionary_version()
    batch_snapshot = getattr(batch, "taxonomy_snapshot", None)
    if not isinstance(batch_snapshot, dict):
        raw_snapshot = _raw(batch).get("taxonomy_snapshot")
        batch_snapshot = raw_snapshot if isinstance(raw_snapshot, dict) else None
    snapshot_version = _clean(
        batch_snapshot.get("source_dictionary_version")
        if isinstance(batch_snapshot, dict)
        else None
    )
    taxonomy_mode = _clean(_value(batch, "taxonomy_resolution_mode"))
    variant_id = _clean(_value(batch, "project_variant_id"))
    if (
        variant_id == BRICK_HOUSE_VARIANT_ID
        and taxonomy_mode == "persisted_snapshot"
        and snapshot_version
        and _SUPPORTED_V65_SNAPSHOT_RE.match(snapshot_version)
    ):
        return False
    if is_legacy_taxonomy_record(batch, current_version=current):
        return True
    return any(is_legacy_taxonomy_record(item, current_version=current) for item in estimates)


def assert_reclassification_allowed(record: Any, *, force_migrate: bool = False) -> None:
    if force_migrate:
        return
    raw = _raw(record)
    locked = bool(raw.get("taxonomy_locked", True))
    if locked and is_legacy_taxonomy_record(record):
        raise LegacyTaxonomyLockedError(
            "Старая смета зафиксирована на версии справочника, использованной при загрузке. "
            "Для переклассификации запустите явную миграцию taxonomy."
        )


def mark_taxonomy_migrated(
    raw: dict[str, Any],
    *,
    from_version: str | None,
    to_version: str | None = None,
) -> dict[str, Any]:
    target = to_version or current_dictionary_version()
    raw["taxonomy_legacy"] = False
    raw["taxonomy_locked"] = True
    raw["taxonomy_resolution_mode"] = "migrated_snapshot"
    raw["classification_migrated_from_version"] = from_version
    raw["classification_migrated_to_version"] = target
    raw["classification_migrated_at"] = datetime.now(timezone.utc).isoformat()
    return raw


def persisted_stage_descriptor(record: Any, fallback_order: int = 0) -> PersistedStageDescriptor | None:
    number = _clean(_value(record, "work_stage_number") or _value(record, "stage_number"))
    title = _clean(_value(record, "work_stage_title") or _value(record, "stage_title"))
    if not number or not title:
        return None
    raw_order = _value(record, "stage_sort_order")
    try:
        sort_order = float(raw_order) if raw_order is not None else _stage_number_sort(number, fallback_order)
    except (TypeError, ValueError):
        sort_order = _stage_number_sort(number, fallback_order)
    floor_number = _value(record, "floor_number")
    try:
        floor_number = int(floor_number) if floor_number is not None else None
    except (TypeError, ValueError):
        floor_number = None
    return PersistedStageDescriptor(
        number=number,
        title=title,
        canonical_stage_id=_clean(_value(record, "canonical_stage_id")),
        stage_instance_id=_clean(_value(record, "stage_instance_id")),
        template_stage_number=_clean(_value(record, "template_stage_number")),
        sort_order=sort_order,
        floor_number=floor_number,
        floor_kind=_clean(_value(record, "floor_kind")),
        floor_label=_clean(_value(record, "floor_label")),
        floor_component=_clean(_value(record, "floor_component")),
        component_role=_clean(_value(record, "component_role")),
        stage_options_mode=_clean(_value(record, "stage_options_mode")) or "none",
    )


def build_persisted_stage_catalog(estimates: Iterable[Any]) -> list[dict[str, Any]]:
    by_number: dict[str, PersistedStageDescriptor] = {}
    for index, estimate in enumerate(estimates):
        descriptor = persisted_stage_descriptor(estimate, fallback_order=index)
        if descriptor is None:
            continue
        current = by_number.get(descriptor.number)
        if current is None or descriptor.sort_order < current.sort_order:
            by_number[descriptor.number] = descriptor
    return [item.as_stage() for item in sorted(by_number.values(), key=lambda item: (item.sort_order, item.number))]


def resolved_stage_title(record: Any, fallback: str | None = None) -> str | None:
    return _clean(_value(record, "work_stage_title") or _value(record, "stage_title")) or _clean(fallback)


def _stage_number_sort(number: str, fallback_order: int) -> float:
    values = [int(part) for part in re.findall(r"\d+", number)]
    if not values:
        return float(10**8 + fallback_order)
    weight = 0.0
    factor = 1_000_000.0
    for value in values[:4]:
        weight += value * factor
        factor /= 1000.0
    return weight + fallback_order / 10000.0
