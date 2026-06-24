"""Read-only rate projection for SessionSubtypeOut / productivity DTOs."""
from __future__ import annotations

from typing import Any

from app.services.work_rate_review_labels import (
    classification_review_label,
    rate_review_label,
)

RATE_SESSION_FIELDS = (
    "operation_code",
    "suggested_operation_code",
    "rate_context_code",
    "selected_rate_item_id",
    "selected_rate_mapping_id",
    "rate_auto_applicable",
    "rate_needs_review",
    "rate_review_reason",
    "rate_selection_source",
    "rate_confidence",
    "rate_unit_code",
    "labor_hours_per_unit_min",
    "labor_hours_per_unit_avg",
    "labor_hours_per_unit_max",
    "calculated_labor_hours_min",
    "calculated_labor_hours_avg",
    "calculated_labor_hours_max",
    "resolved_labor_hours",
    "resolved_labor_source",
    "classification_needs_review",
    "classification_review_reason",
    "suggested_taxonomy_code",
)


def session_subtype_rate_projection(raw_data: dict[str, Any] | None) -> dict[str, Any]:
    """Return current selected-rate data without creating a second source of truth."""
    raw = raw_data or {}
    result = {field: raw.get(field) for field in RATE_SESSION_FIELDS}
    result["classification_review_label"] = classification_review_label(
        result.get("classification_review_reason")
    )
    result["rate_review_label"] = rate_review_label(
        result.get("rate_review_reason")
    )
    return result
