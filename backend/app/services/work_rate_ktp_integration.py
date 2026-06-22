"""Framework-neutral helpers for connecting selected rates to KTP/Gantt rows."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.work_rate_models import RateSelectionResult, WorkRateItem
from app.services.work_rate_selection_service import LaborResolution, WorkRateSelectionService


NON_BLOCKING_RATE_REVIEW_REASONS = {None, "quantity_missing"}


def build_calculation_group_key(
    *,
    project_id: str,
    parent_work_id: str | None = None,
    section_block_id: str | None = None,
    taxonomy_code: str | None = None,
    object_scope_code: str | None = None,
    volume_scope: str | None = None,
) -> str:
    parent = parent_work_id or section_block_id or "ungrouped"
    raw = "|".join(
        str(value or "")
        for value in (project_id, parent, taxonomy_code, object_scope_code, volume_scope)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def apply_rate_to_raw_data(
    raw_data: dict[str, Any] | None,
    *,
    selection: RateSelectionResult,
    rate_item: WorkRateItem | None,
    quantity: float | None,
    quantity_unit: str | None,
    labor_source_mode: str,
    manual_labor_hours: float | None = None,
    project_specific_labor_hours: float | None = None,
    fer_labor_hours: float | None = None,
    calculation_group_key: str | None = None,
) -> dict[str, Any]:
    raw = dict(raw_data or {})
    calculation: dict[str, Any] = {}
    if rate_item is not None:
        calculation = WorkRateSelectionService.calculate_labor(
            quantity=quantity,
            quantity_unit=quantity_unit,
            rate_item=rate_item,
        )

    catalog_independent = None
    catalog_derived = None
    if rate_item is not None:
        labor_total = calculation.get("labor_avg_total")
        if rate_item.labor_basis in {"normative", "independent_market_estimate", "manual"}:
            catalog_independent = labor_total
        elif rate_item.labor_basis == "derived_from_price":
            catalog_derived = labor_total

    resolved: LaborResolution = WorkRateSelectionService.resolve_labor_source(
        labor_source_mode=labor_source_mode,
        manual_labor_hours=manual_labor_hours,
        project_specific_labor_hours=project_specific_labor_hours,
        catalog_independent_labor_hours=catalog_independent,
        fer_labor_hours=fer_labor_hours,
        catalog_derived_labor_hours=catalog_derived,
    )
    conversion_factor = selection.unit_conversion_factor
    effective_labor = {
        key: (round(float(value) * float(conversion_factor), 8) if value is not None and conversion_factor is not None else None)
        for key, value in {
            "min": selection.labor_min,
            "avg": selection.labor_avg,
            "max": selection.labor_max,
        }.items()
    }
    rate_auto_applicable = bool(
        selection.rate_auto_applicable
        and selection.rate_item_id
        and conversion_factor is not None
        and effective_labor["avg"] is not None
        and effective_labor["avg"] > 0
        and selection.review_reason in NON_BLOCKING_RATE_REVIEW_REASONS
    )

    raw.update(
        {
            "operation_code": selection.operation_code,
            "selected_rate_item_id": selection.rate_item_id,
            "selected_rate_mapping_id": selection.rate_mapping_id,
            "rate_selection_source": selection.selection_source,
            "rate_confidence": selection.selection_confidence,
            "rate_auto_applicable": rate_auto_applicable,
            "rate_needs_review": selection.needs_review or resolved.needs_review,
            "rate_review_reason": selection.review_reason or resolved.reason,
            "rate_unit_code": selection.unit_code,
            "item_unit_code": selection.item_unit_code or quantity_unit,
            "unit_conversion_factor": conversion_factor,
            "rate_price_min": selection.price_min,
            "rate_price_max": selection.price_max,
            "rate_price_avg": selection.price_avg,
            "labor_hours_per_unit_min": selection.labor_min,
            "labor_hours_per_unit_max": selection.labor_max,
            "labor_hours_per_unit_avg": selection.labor_avg,
            "effective_labor_hours_per_unit_min": effective_labor["min"],
            "effective_labor_hours_per_unit_avg": effective_labor["avg"],
            "effective_labor_hours_per_unit_max": effective_labor["max"],
            "calculated_labor_hours_min": calculation.get("labor_min_total"),
            "calculated_labor_hours_avg": calculation.get("labor_avg_total"),
            "calculated_labor_hours_max": calculation.get("labor_max_total"),
            "resolved_labor_hours": resolved.resolved_labor_hours,
            "resolved_labor_source": resolved.resolved_labor_source,
            "labor_source_mode": labor_source_mode,
            "calculation_group_key": calculation_group_key,
            "rate_calculation_payload": {
                "selection": selection.as_dict(),
                "calculation": calculation,
                "resolution": resolved.as_dict(),
            },
        }
    )
    return raw


def rate_diagnostics_json(raw_data: dict[str, Any] | None) -> str:
    raw = raw_data or {}
    return json.dumps(
        {
            key: value
            for key, value in raw.items()
            if key.startswith("rate_")
            or key.startswith("labor_")
            or key.startswith("calculated_labor_")
            or key.startswith("resolved_labor_")
            or key == "operation_code"
            or key == "calculation_group_key"
        },
        ensure_ascii=False,
        indent=2,
    )
