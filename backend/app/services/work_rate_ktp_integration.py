"""Framework-neutral helpers for connecting selected rates to KTP/Gantt rows."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.work_rate_models import RateSelectionResult, WorkRateItem
from app.services.work_rate_selection_service import LaborResolution, WorkRateSelectionService


def build_calculation_group_key(
    *,
    project_id: str,
    parent_work_id: str | None = None,
    section_block_id: str | None = None,
    taxonomy_code: str | None = None,
    object_scope_code: str | None = None,
    volume_scope: str | None = None,
    estimate_batch_id: str | None = None,
    stage_instance_id: str | None = None,
    operation_package_code: str | None = None,
    work_scope_key: str | None = None,
) -> str:
    # Stage-7 scope.  It prevents a package on one floor or constructive area
    # from conflicting with atomic rows on another.  Legacy callers retain the
    # previous key shape when no projection-aware fields are supplied.
    if stage_instance_id or operation_package_code or work_scope_key:
        raw = "|".join(
            str(value or "")
            for value in (
                estimate_batch_id or project_id,
                stage_instance_id,
                operation_package_code,
                work_scope_key,
            )
        )
    else:
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
    subtype_output_per_day: float | None = None,
    crew_size: int | None = None,
    hours_per_day: float = 8.0,
    calculation_group_key: str | None = None,
) -> dict[str, Any]:
    raw = dict(raw_data or {})
    calculation: dict[str, Any] = {}
    calculation_item = rate_item
    if selection.user_override_id and selection.unit_code:
        calculation_item = WorkRateItem(
            id=selection.rate_item_id or "user-override",
            unit_code=selection.unit_code,
            norm_base_quantity=selection.norm_base_quantity or 1.0,
            labor_min=selection.labor_min,
            labor_avg=selection.labor_avg,
            labor_max=selection.labor_max,
            labor_basis=selection.labor_basis or "user_override",
        )
    if calculation_item is not None:
        calculation = WorkRateSelectionService.calculate_labor(
            quantity=quantity,
            quantity_unit=quantity_unit,
            rate_item=calculation_item,
        )

    catalog_independent = None
    catalog_derived = None
    if calculation_item is not None and selection.rate_auto_applicable:
        labor_total = calculation.get("labor_avg_total")
        if calculation_item.labor_basis in {"normative", "independent_market_estimate", "manual", "provisional_engineer_norm", "user_override"}:
            catalog_independent = labor_total
        elif calculation_item.labor_basis == "derived_from_price":
            catalog_derived = labor_total

    resolved: LaborResolution = WorkRateSelectionService.resolve_labor_source(
        labor_source_mode=labor_source_mode,
        manual_labor_hours=manual_labor_hours,
        project_specific_labor_hours=project_specific_labor_hours,
        catalog_independent_labor_hours=catalog_independent,
        fer_labor_hours=fer_labor_hours,
        catalog_derived_labor_hours=catalog_derived,
        subtype_output_per_day=subtype_output_per_day,
        quantity=quantity,
        crew_size=crew_size,
        hours_per_day=hours_per_day,
    )

    raw.update(
        {
            "operation_code": selection.operation_code,
            "suggested_operation_code": selection.suggested_operation_code,
            "rate_context_code": selection.rate_context_code,
            "rate_auto_applicable": selection.rate_auto_applicable,
            "selected_rate_item_id": selection.rate_item_id,
            "selected_rate_mapping_id": selection.rate_mapping_id,
            "rate_selection_source": selection.selection_source,
            "rate_confidence": selection.selection_confidence,
            "rate_needs_review": selection.needs_review or resolved.needs_review,
            "rate_review_reason": selection.review_reason or resolved.reason,
            "rate_unit_code": selection.unit_code,
            "rate_price_min": selection.price_min,
            "rate_price_max": selection.price_max,
            "rate_price_avg": selection.price_avg,
            "labor_hours_per_unit_min": selection.labor_min,
            "labor_hours_per_unit_max": selection.labor_max,
            "labor_hours_per_unit_avg": selection.labor_avg,
            "norm_base_quantity": selection.norm_base_quantity,
            "source_rate_id": selection.source_rate_id,
            "rate_value_mode": selection.rate_value_mode,
            "rate_resolution_status": selection.resolution_status,
            "rate_requires_user_input": selection.requires_user_input,
            "user_work_rate_override_id": selection.user_override_id,
            "user_work_rate_override_scope": selection.user_override_scope,
            "user_work_rate_override_owner_id": selection.user_override_owner_id,
            "rate_applicability_hash": selection.applicability_hash,
            "rate_applicability": selection.applicability_json,
            "user_rate_input_request": ({
                "source_rate_id": selection.source_rate_id,
                "selected_target_code": selection.operation_code,
                "unit_code": selection.unit_code,
                "norm_base_quantity": selection.norm_base_quantity,
                "applicability": selection.applicability_json,
                "accepted_input_units": ["person_shift", "person_hour"],
            } if selection.requires_user_input else None),
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
            or key in {
                "operation_code",
                "suggested_operation_code",
                "classification_needs_review",
                "classification_review_reason",
                "suggested_taxonomy_code",
                "calculation_group_key",
            }
        },
        ensure_ascii=False,
        indent=2,
    )
