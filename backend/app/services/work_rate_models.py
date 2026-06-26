"""Domain models for the work-rate catalogue.

The production backend may persist these objects with SQLAlchemy.  The service
layer deliberately uses plain dataclasses so the importer/matcher can be tested
without a database and embedded into the existing backend incrementally.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())


SOURCE_NORMALIZED = "normalized_rate_catalog"
SOURCE_OBSERVATION = "market_estimate_observation"
SOURCE_MANUAL = "manual_catalog"
SOURCE_NORMATIVE = "external_normative"

MAPPING_DIRECT = "direct"
MAPPING_CONTEXTUAL = "contextual"
MAPPING_PACKAGE = "package"
MAPPING_EXCLUDED = "excluded"
MAPPING_OBSERVATION = "observation"
MAPPING_UNMAPPED = "unmapped"

MAPPING_MODES = {
    MAPPING_DIRECT,
    MAPPING_CONTEXTUAL,
    MAPPING_PACKAGE,
    MAPPING_EXCLUDED,
    MAPPING_OBSERVATION,
    MAPPING_UNMAPPED,
}

REVIEW_NEW = "new"
REVIEW_AUTO = "auto_mapped"
REVIEW_NEEDED = "needs_review"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"

MAPPING_STATUS_UNMAPPED = "unmapped"
MAPPING_STATUS_MAPPED = "mapped"
MAPPING_STATUS_PARTIAL = "partially_mapped"
MAPPING_STATUS_EXCLUDED = "excluded"
MAPPING_STATUS_OBSERVATION = "observation"
MAPPING_STATUS_ORPHANED = "orphaned"

LABOR_DERIVED = "derived_from_price"
LABOR_INDEPENDENT = "independent_market_estimate"
LABOR_NORMATIVE = "normative"
LABOR_MANUAL = "manual"
LABOR_UNKNOWN = "unknown"


@dataclass(slots=True)
class WorkRateSource:
    id: str = field(default_factory=new_id)
    name: str = ""
    source_kind: str = SOURCE_NORMALIZED
    source_file: str = ""
    source_sheet: str | None = None
    source_version: str = "1"
    valid_from: str | None = None
    valid_to: str | None = None
    region: str | None = None
    currency: str = "RUB"
    hourly_rate: float | None = None
    labor_basis: str | None = None
    is_active: bool = True
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkRateItem:
    id: str = field(default_factory=new_id)
    source_id: str = ""
    source_row: int = 0
    external_code: str | None = None
    stable_row_key: str = ""
    row_content_hash: str = ""
    revision: int = 1
    supersedes_rate_item_id: str | None = None

    name: str = ""
    normalized_name: str = ""
    notes: str | None = None
    normalized_notes: str | None = None

    unit_raw: str | None = None
    unit_code: str | None = None
    unit_dimension: str | None = None

    quantity: float | None = None
    price_min: float | None = None
    price_max: float | None = None
    price_avg: float | None = None
    total_price: float | None = None

    labor_min: float | None = None
    labor_max: float | None = None
    labor_avg: float | None = None
    hourly_rate: float | None = None
    labor_basis: str | None = None
    norm_base_quantity: float = 1.0
    source_rate_id: str | None = None
    rate_value_mode: str = "legacy_catalog"
    resolution_status: str = "source_value_available"
    applicability_json: dict[str, Any] = field(default_factory=dict)

    mapping_status: str = MAPPING_STATUS_UNMAPPED
    has_active_mapping: bool = False
    is_package_candidate: bool = False
    review_status: str = REVIEW_NEW
    review_reason: str | None = None
    approved_as_rate: bool = False
    auto_applicable: bool = False
    is_active: bool = True

    row_role: str = "work"
    source_payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkRateMapping:
    id: str = field(default_factory=new_id)
    rate_item_id: str = ""
    operation_code: str | None = None
    taxonomy_section_id: str | None = None
    taxonomy_subtype_id: str | None = None
    taxonomy_code: str | None = None
    object_scope_code: str | None = None
    rate_context_code: str | None = None
    mapping_mode: str = MAPPING_UNMAPPED
    priority: int = 100
    confidence: float = 0.0
    mapping_source: str = "automatic"
    taxonomy_version: str = ""
    operation_policy_version: str = ""
    is_primary: bool = True
    is_active: bool = True
    approved_by: str | None = None
    approved_at: str | None = None
    included_operations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkRateImportRun:
    id: str = field(default_factory=new_id)
    source_id: str | None = None
    filename: str = ""
    file_hash: str = ""
    status: str = "pending"
    rows_total: int = 0
    rows_imported: int = 0
    rows_skipped: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_unmapped: int = 0
    rows_needs_review: int = 0
    errors_json: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=utcnow_iso)
    finished_at: str | None = None
    created_by: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkRateImportResult:
    source: WorkRateSource
    run: WorkRateImportRun
    items: list[WorkRateItem]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.as_dict(),
            "run": self.run.as_dict(),
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(slots=True)
class RateSelectionResult:
    rate_item_id: str | None = None
    rate_mapping_id: str | None = None
    selection_source: str | None = None
    selection_confidence: float = 0.0
    operation_code: str | None = None
    taxonomy_code: str | None = None
    object_scope_code: str | None = None
    rate_context_code: str | None = None
    suggested_operation_code: str | None = None
    rate_auto_applicable: bool = False
    unit_code: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    price_avg: float | None = None
    labor_min: float | None = None
    labor_max: float | None = None
    labor_avg: float | None = None
    labor_basis: str | None = None
    norm_base_quantity: float = 1.0
    source_rate_id: str | None = None
    rate_value_mode: str | None = None
    resolution_status: str | None = None
    requires_user_input: bool = False
    user_override_id: str | None = None
    user_override_scope: str | None = None
    user_override_owner_id: str | None = None
    applicability_hash: str | None = None
    applicability_json: dict[str, Any] = field(default_factory=dict)
    needs_review: bool = False
    review_reason: str | None = None
    review_sub_reason: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkRateCalculationRow:
    row_id: str
    calculation_group_key: str
    operation_code: str | None
    rate_item_id: str | None = None
    rate_mapping_id: str | None = None
    package_resolution_mode: str | None = None
    taxonomy_code: str | None = None
    object_scope_code: str | None = None


@dataclass(slots=True)
class PackageConflict:
    calculation_group_key: str
    package_rate_item_ids: list[str]
    atomic_rate_item_ids: list[str]
    conflicting_operation_codes: list[str]
    resolution: str = "manual_required"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
