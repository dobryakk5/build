"""Rate selection, labour calculations and package-conflict detection."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from app.services.work_rate_models import (
    LABOR_DERIVED,
    LABOR_INDEPENDENT,
    LABOR_NORMATIVE,
    MAPPING_EXCLUDED,
    MAPPING_OBSERVATION,
    MAPPING_UNMAPPED,
    PackageConflict,
    RateSelectionResult,
    SOURCE_MANUAL,
    SOURCE_NORMALIZED,
    SOURCE_NORMATIVE,
    SOURCE_OBSERVATION,
    WorkRateCalculationRow,
    WorkRateItem,
    WorkRateMapping,
    WorkRateSource,
)


@dataclass(slots=True)
class LaborResolution:
    resolved_labor_hours: float | None
    resolved_labor_source: str | None
    needs_review: bool = False
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved_labor_hours": self.resolved_labor_hours,
            "resolved_labor_source": self.resolved_labor_source,
            "needs_review": self.needs_review,
            "reason": self.reason,
        }


# factor means: value in source unit * factor = value in target unit.
UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    ("kg", "t"): 0.001,
    ("t", "kg"): 1000.0,
    ("mm", "m"): 0.001,
    ("m", "mm"): 1000.0,
}


class WorkRateSelectionService:
    def __init__(self, operation_packages: dict[str, dict[str, Any]] | None = None):
        self.operation_packages = operation_packages or {}

    @staticmethod
    def unit_conversion_factor(source_unit: str | None, target_unit: str | None) -> float | None:
        if not source_unit or not target_unit:
            return None
        if source_unit == target_unit:
            return 1.0
        return UNIT_CONVERSIONS.get((source_unit, target_unit))

    @staticmethod
    def _source_priority(source: WorkRateSource) -> int:
        if source.source_kind == SOURCE_MANUAL:
            return 500
        if source.source_kind == SOURCE_NORMATIVE:
            return 400
        if source.source_kind == SOURCE_NORMALIZED:
            return 300
        if source.source_kind == SOURCE_OBSERVATION:
            return 100
        return 0

    def select_rate(
        self,
        *,
        taxonomy_code: str,
        operation_code: str,
        object_scope_code: str | None,
        quantity: float | None,
        unit_code: str | None,
        items: Iterable[WorkRateItem],
        mappings: Iterable[WorkRateMapping],
        sources: Iterable[WorkRateSource],
    ) -> RateSelectionResult:
        item_by_id = {item.id: item for item in items if item.is_active}
        source_by_id = {source.id: source for source in sources if source.is_active}
        ranked: list[tuple[int, float, WorkRateItem, WorkRateMapping, float]] = []
        incompatible_unit_seen = False

        for mapping in mappings:
            if not mapping.is_active:
                continue
            if mapping.mapping_mode in {MAPPING_EXCLUDED, MAPPING_UNMAPPED}:
                continue
            if mapping.operation_code != operation_code:
                continue
            if mapping.taxonomy_code != taxonomy_code:
                continue
            if mapping.object_scope_code and object_scope_code and mapping.object_scope_code != object_scope_code:
                continue
            item = item_by_id.get(mapping.rate_item_id)
            if item is None or not item.has_active_mapping:
                continue
            source = source_by_id.get(item.source_id)
            if source is None:
                continue
            # Observation is never auto-used unless explicitly approved.
            if source.source_kind == SOURCE_OBSERVATION and not item.approved_as_rate:
                continue
            factor = self.unit_conversion_factor(unit_code, item.unit_code)
            if factor is None:
                incompatible_unit_seen = True
                continue
            priority = self._source_priority(source)
            if source.source_kind == SOURCE_OBSERVATION and item.approved_as_rate:
                priority = 450  # manually approved project-specific evidence
            ranked.append((priority, mapping.confidence, item, mapping, factor))

        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        if not ranked:
            return RateSelectionResult(
                operation_code=operation_code,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                unit_code=unit_code,
                item_unit_code=unit_code,
                needs_review=True,
                review_reason="unit_incompatible" if incompatible_unit_seen else "no_approved_compatible_rate",
            )

        top_priority, top_confidence, top_item, top_mapping, conversion = ranked[0]
        equivalent = [row for row in ranked if row[0] == top_priority and abs(row[1] - top_confidence) < 0.02]
        candidates = [
            {
                "rate_item_id": item.id,
                "rate_mapping_id": mapping.id,
                "source_id": item.source_id,
                "name": item.name,
                "unit_code": item.unit_code,
                "price_avg": item.price_avg,
                "labor_avg": item.labor_avg,
                "confidence": confidence,
                "conversion_factor": factor,
            }
            for _, confidence, item, mapping, factor in ranked[:10]
        ]
        if len(equivalent) > 1:
            return RateSelectionResult(
                operation_code=operation_code,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                unit_code=unit_code,
                item_unit_code=unit_code,
                needs_review=True,
                review_reason="multiple_equivalent_rate_candidates",
                candidates=candidates,
            )

        source = source_by_id[top_item.source_id]
        selection_source = "project_specific" if (
            source.source_kind == SOURCE_MANUAL
            or (source.source_kind == SOURCE_OBSERVATION and top_item.approved_as_rate)
        ) else source.source_kind
        rate_auto_applicable = bool(
            top_item.auto_applicable
            and top_item.labor_avg is not None
            and float(top_item.labor_avg) > 0
        )
        needs_review = quantity is None or quantity <= 0 or not rate_auto_applicable
        review_reason = "quantity_missing" if quantity is None or quantity <= 0 else None
        if not rate_auto_applicable:
            review_reason = top_item.review_reason or "rate_not_approved"

        return RateSelectionResult(
            rate_item_id=top_item.id,
            rate_mapping_id=top_mapping.id,
            selection_source=selection_source,
            selection_confidence=top_confidence,
            operation_code=operation_code,
            taxonomy_code=taxonomy_code,
            object_scope_code=object_scope_code,
            unit_code=top_item.unit_code,
            item_unit_code=unit_code,
            rate_unit_code=top_item.unit_code,
            unit_conversion_factor=conversion,
            price_min=top_item.price_min,
            price_max=top_item.price_max,
            price_avg=top_item.price_avg,
            labor_min=top_item.labor_min,
            labor_max=top_item.labor_max,
            labor_avg=top_item.labor_avg,
            labor_basis=top_item.labor_basis,
            rate_auto_applicable=rate_auto_applicable,
            needs_review=needs_review,
            review_reason=review_reason,
            candidates=candidates,
        )

    @staticmethod
    def calculate_labor(
        *,
        quantity: float | None,
        quantity_unit: str | None,
        rate_item: WorkRateItem,
    ) -> dict[str, float | None | str]:
        if quantity is None or quantity <= 0:
            return {
                "labor_min_total": None,
                "labor_avg_total": None,
                "labor_max_total": None,
                "needs_review": "quantity_missing",
            }
        factor = WorkRateSelectionService.unit_conversion_factor(quantity_unit, rate_item.unit_code)
        if factor is None:
            return {
                "labor_min_total": None,
                "labor_avg_total": None,
                "labor_max_total": None,
                "needs_review": "unit_incompatible",
            }
        rate_quantity = float(quantity) * factor
        return {
            "labor_min_total": round(rate_quantity * rate_item.labor_min, 4) if rate_item.labor_min is not None else None,
            "labor_avg_total": round(rate_quantity * rate_item.labor_avg, 4) if rate_item.labor_avg is not None else None,
            "labor_max_total": round(rate_quantity * rate_item.labor_max, 4) if rate_item.labor_max is not None else None,
            "needs_review": None,
        }

    @staticmethod
    def calculate_duration(
        labor_hours: float | None,
        *,
        crew_size: int | None,
        hours_per_day: float = 8.0,
    ) -> int | None:
        if labor_hours is None or labor_hours <= 0 or not crew_size or crew_size <= 0 or hours_per_day <= 0:
            return None
        return max(1, math.ceil(labor_hours / (crew_size * hours_per_day)))

    @staticmethod
    def output_per_day(
        *,
        crew_size: int | None,
        hours_per_day: float,
        labor_hours_per_unit: float | None,
    ) -> float | None:
        if not crew_size or crew_size <= 0 or hours_per_day <= 0 or not labor_hours_per_unit or labor_hours_per_unit <= 0:
            return None
        return round(crew_size * hours_per_day / labor_hours_per_unit, 4)

    @staticmethod
    def resolve_labor_source(
        *,
        labor_source_mode: str,
        manual_labor_hours: float | None = None,
        project_specific_labor_hours: float | None = None,
        catalog_independent_labor_hours: float | None = None,
        fer_labor_hours: float | None = None,
        catalog_derived_labor_hours: float | None = None,
    ) -> LaborResolution:
        if manual_labor_hours is not None and manual_labor_hours > 0:
            return LaborResolution(manual_labor_hours, "manual")

        sources: list[tuple[str, float | None]]
        if labor_source_mode == "manual":
            return LaborResolution(None, None, True, "manual_labor_required")
        if labor_source_mode == "rate_catalog":
            sources = [
                ("project_specific_rate", project_specific_labor_hours),
                ("catalog_independent", catalog_independent_labor_hours),
                ("catalog_derived", catalog_derived_labor_hours),
            ]
        elif labor_source_mode == "fer":
            sources = [
                ("fer", fer_labor_hours),
            ]
        elif labor_source_mode == "hybrid":
            sources = [
                ("project_specific_rate", project_specific_labor_hours),
                ("catalog_independent", catalog_independent_labor_hours),
                ("fer", fer_labor_hours),
                ("catalog_derived", catalog_derived_labor_hours),
            ]
        else:
            return LaborResolution(None, None, True, "unknown_labor_source_mode")

        for source, value in sources:
            if value is not None and value > 0:
                return LaborResolution(float(value), source)
        return LaborResolution(None, None, True, "labor_source_not_available")

    def detect_package_conflicts(
        self,
        rows: Iterable[WorkRateCalculationRow],
    ) -> list[PackageConflict]:
        groups: dict[str, list[WorkRateCalculationRow]] = defaultdict(list)
        for row in rows:
            groups[row.calculation_group_key].append(row)
        conflicts: list[PackageConflict] = []

        for group_key, group_rows in groups.items():
            operations = {row.operation_code for row in group_rows if row.operation_code}
            package_rows: list[WorkRateCalculationRow] = []
            atomic_rows: list[WorkRateCalculationRow] = []
            conflicting_codes: set[str] = set()
            for row in group_rows:
                if not row.operation_code:
                    continue
                package = self.operation_packages.get(row.operation_code)
                if not package:
                    continue
                included = set(package.get("included_operations") or [])
                present = included & operations
                if present:
                    package_rows.append(row)
                    conflicting_codes.update(present)
                    atomic_rows.extend(r for r in group_rows if r.operation_code in present)
            if package_rows:
                conflicts.append(
                    PackageConflict(
                        calculation_group_key=group_key,
                        package_rate_item_ids=sorted({row.rate_item_id for row in package_rows if row.rate_item_id}),
                        atomic_rate_item_ids=sorted({row.rate_item_id for row in atomic_rows if row.rate_item_id}),
                        conflicting_operation_codes=sorted(conflicting_codes),
                    )
                )
        return conflicts
