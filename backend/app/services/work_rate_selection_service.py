"""Rate selection, labour calculations and package-conflict detection."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from app.services.work_context_rules import (
    build_rate_context_text,
    resolve_masonry_context,
    resolve_roof_covering_context,
    resolve_special_masonry_operation,
)
from app.services.user_work_rate_override_service import (
    UserWorkRateOverride,
    canonical_applicability_hash,
    normalize_applicability,
)
from app.services.work_rate_models import (
    MAPPING_EXCLUDED,
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

    @staticmethod
    def _item_applicability_matches(
        item: WorkRateItem,
        actual: dict[str, Any] | None,
    ) -> bool:
        expected = item.applicability_json or (item.source_payload or {}).get("applicability") or {}
        if not expected:
            return True
        actual = actual or {}
        checks = {
            "project_variant_ids": "project_variant_id",
            "template_stage_numbers": "template_stage_number",
            "semantic_stage_option_ids": "semantic_stage_option_id",
            "floor_numbers": "floor_number",
            "floor_kinds": "floor_kind",
            "rate_context_codes": "rate_context_code",
        }
        for expected_key, actual_key in checks.items():
            allowed = expected.get(expected_key)
            value = actual.get(actual_key)
            if allowed and expected_key == "project_variant_ids" and value is None:
                return False
            if allowed and value is not None and value not in set(allowed):
                return False
        for expected_key in ("roof_covering_material", "base_type"):
            expected_value = expected.get(expected_key)
            if expected_value in (None, ""):
                continue
            actual_value = actual.get(expected_key)
            if actual_value in (None, ""):
                return False
            if isinstance(expected_value, list | tuple | set):
                if actual_value not in set(expected_value):
                    return False
            elif actual_value != expected_value:
                return False
        return True

    @staticmethod
    def _override_for_item(
        *,
        item: WorkRateItem,
        operation_code: str,
        user_id: str | None,
        user_overrides: Iterable[UserWorkRateOverride] | None,
        applicability: dict[str, Any] | None,
    ) -> UserWorkRateOverride | None:
        if not user_id or not item.source_rate_id:
            return None
        expected_hash = canonical_applicability_hash(applicability)
        for row in user_overrides or ():
            if not row.is_active or row.user_id != str(user_id):
                continue
            if row.source_rate_id != item.source_rate_id:
                continue
            if row.selected_target_code != operation_code:
                continue
            if row.unit_code != str(item.unit_code or ""):
                continue
            if abs(float(row.norm_base_quantity) - float(item.norm_base_quantity or 1)) > 1e-9:
                continue
            if row.applicability_hash != expected_hash:
                continue
            return row
        return None

    def select_rate(
        self,
        *,
        taxonomy_code: str,
        operation_code: str,
        object_scope_code: str | None,
        quantity: float | None,
        unit_code: str | None,
        work_name: str | None = None,
        item_text: str | None = None,
        spec: str | None = None,
        section_title: str | None = None,
        section_description: str | None = None,
        section_parent_context: str | None = None,
        items: Iterable[WorkRateItem],
        mappings: Iterable[WorkRateMapping],
        sources: Iterable[WorkRateSource],
        user_id: str | None = None,
        user_overrides: Iterable[UserWorkRateOverride] | None = None,
        applicability: dict[str, Any] | None = None,
    ) -> RateSelectionResult:
        work_text, section_context_text, source_context_text = build_rate_context_text(
            work_name=work_name,
            item_text=item_text,
            spec=spec,
            section_title=section_title,
            section_description=section_description,
            section_parent_context=section_parent_context,
        )
        special_operation = resolve_special_masonry_operation(
            work_text,
            section_context_text,
        )
        expected_taxonomy = {
            "facade_cladding": "interior_finishing/facade_finishing",
            "arm_belt_masonry": "load_bearing_walls/arm_belts_lintels",
            "vent_shaft_masonry": "load_bearing_walls/vent_shafts_masonry",
        }
        effective_operation = operation_code
        suggested_operation: str | None = None
        if special_operation and special_operation != operation_code:
            suggested_operation = special_operation
            expected = expected_taxonomy.get(special_operation)
            if expected and taxonomy_code != expected:
                return RateSelectionResult(
                    operation_code=operation_code,
                    suggested_operation_code=special_operation,
                    taxonomy_code=taxonomy_code,
                    object_scope_code=object_scope_code,
                    unit_code=unit_code,
                    needs_review=True,
                    review_reason="special_masonry_operation_mismatch",
                    rate_auto_applicable=False,
                )
            effective_operation = special_operation
        effective_applicability = dict(applicability or {})
        roof_context_result = None
        if effective_operation == "roof_covering_installation":
            roof_context_result = resolve_roof_covering_context(source_context_text)
            if roof_context_result.context_code:
                effective_applicability.setdefault("rate_context_code", roof_context_result.context_code)
            for key, value in (roof_context_result.applicability or {}).items():
                effective_applicability.setdefault(key, value)

        item_by_id = {item.id: item for item in items if item.is_active}
        source_by_id = {source.id: source for source in sources if source.is_active}
        operation_candidates: list[tuple[WorkRateItem, WorkRateMapping, WorkRateSource]] = []

        for mapping in mappings:
            if not mapping.is_active:
                continue
            if mapping.mapping_mode in {MAPPING_EXCLUDED, MAPPING_UNMAPPED}:
                continue
            if mapping.operation_code != effective_operation:
                continue
            if mapping.taxonomy_code and mapping.taxonomy_code != taxonomy_code:
                continue
            if (
                mapping.object_scope_code
                and object_scope_code
                and mapping.object_scope_code != object_scope_code
            ):
                continue
            item = item_by_id.get(mapping.rate_item_id)
            if item is None or not item.has_active_mapping:
                continue
            source = source_by_id.get(item.source_id)
            if source is None:
                continue
            if source.source_kind == SOURCE_OBSERVATION and not item.approved_as_rate:
                continue
            if not self._item_applicability_matches(item, effective_applicability):
                continue
            operation_candidates.append((item, mapping, source))

        if not operation_candidates:
            reason = {
                "brick_pillar_masonry": "brick_pillar_rate_not_available",
                "vent_shaft_masonry": "vent_shaft_masonry_rate_not_available",
                "facade_cladding": "facade_cladding_rate_not_available",
            }.get(effective_operation, "no_approved_compatible_rate")
            return RateSelectionResult(
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason=reason,
                rate_auto_applicable=False,
            )

        compatible: list[tuple[WorkRateItem, WorkRateMapping, WorkRateSource, float]] = []
        for item, mapping, source in operation_candidates:
            factor = self.unit_conversion_factor(unit_code, item.unit_code)
            if factor is not None:
                compatible.append((item, mapping, source, factor))

        if not compatible:
            return RateSelectionResult(
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason="unit_incompatible",
                rate_auto_applicable=False,
                candidates=[
                    {
                        "rate_item_id": item.id,
                        "rate_mapping_id": mapping.id,
                        "name": item.name,
                        "unit_code": item.unit_code,
                        "rate_context_code": mapping.rate_context_code,
                    }
                    for item, mapping, _source in operation_candidates[:10]
                ],
            )

        selected_context: str | None = None
        if effective_operation == "brick_masonry":
            context_result = resolve_masonry_context(source_context_text)
            selected_context = context_result.context_code
            contextual_codes = {
                mapping.rate_context_code
                for _item, mapping, _source, _factor in compatible
                if mapping.rate_context_code in {
                    "exterior_wall", "interior_wall", "frame_infill"
                }
            }
            if context_result.needs_review and contextual_codes:
                return RateSelectionResult(
                    operation_code=effective_operation,
                    suggested_operation_code=suggested_operation,
                    taxonomy_code=taxonomy_code,
                    object_scope_code=object_scope_code,
                    rate_context_code=None,
                    unit_code=unit_code,
                    needs_review=True,
                    review_reason=context_result.review_reason,
                    rate_auto_applicable=False,
                )
            if selected_context:
                exact = [row for row in compatible if row[1].rate_context_code == selected_context]
                no_context = [row for row in compatible if row[1].rate_context_code is None]
                compatible = exact if exact else no_context
                if not compatible:
                    return RateSelectionResult(
                        operation_code=effective_operation,
                        suggested_operation_code=suggested_operation,
                        taxonomy_code=taxonomy_code,
                        object_scope_code=object_scope_code,
                        rate_context_code=selected_context,
                        unit_code=unit_code,
                        needs_review=True,
                        review_reason="no_approved_compatible_rate",
                        rate_auto_applicable=False,
                    )
        elif effective_operation == "facade_cladding":
            exact = [row for row in compatible if row[1].rate_context_code == "facade"]
            no_context = [row for row in compatible if row[1].rate_context_code is None]
            compatible = exact if exact else no_context
            selected_context = "facade"
        elif effective_operation == "arm_belt_masonry":
            exact = [row for row in compatible if row[1].rate_context_code == "brick_arm_belt"]
            no_context = [row for row in compatible if row[1].rate_context_code is None]
            compatible = exact if exact else no_context
            selected_context = "brick_arm_belt"
        elif effective_operation == "roof_covering_installation":
            selected_context = roof_context_result.context_code if roof_context_result else None
            contextual_codes = {
                mapping.rate_context_code
                for _item, mapping, _source, _factor in compatible
                if mapping.rate_context_code in {"metal_tile", "flexible_shingles"}
            }
            if selected_context:
                exact = [row for row in compatible if row[1].rate_context_code == selected_context]
                no_context = [row for row in compatible if row[1].rate_context_code is None]
                compatible = exact if exact else no_context
            elif contextual_codes:
                return RateSelectionResult(
                    operation_code=effective_operation,
                    suggested_operation_code=suggested_operation,
                    taxonomy_code=taxonomy_code,
                    object_scope_code=object_scope_code,
                    rate_context_code=None,
                    unit_code=unit_code,
                    needs_review=True,
                    review_reason=(roof_context_result.review_reason if roof_context_result else "roof_covering_material_not_resolved"),
                    rate_auto_applicable=False,
                )

        # A source row marked "по факту" is a hard user-scoped gate.
        # It must never silently fall through to a global rate.
        placeholders = [row for row in compatible if row[0].rate_value_mode == "user_defined_on_first_use"]
        if placeholders:
            placeholder_candidates: list[dict[str, Any]] = []
            for item, mapping, _source, factor in placeholders:
                override = self._override_for_item(
                    item=item,
                    operation_code=effective_operation,
                    user_id=user_id,
                    user_overrides=user_overrides,
                    applicability=effective_applicability,
                )
                placeholder_candidates.append({
                    "rate_item_id": item.id,
                    "rate_mapping_id": mapping.id,
                    "source_rate_id": item.source_rate_id,
                    "name": item.name,
                    "unit_code": item.unit_code,
                    "norm_base_quantity": item.norm_base_quantity,
                    "conversion_factor": factor,
                    "requires_user_input": override is None,
                })
                if override is not None:
                    quantity_missing = quantity is None or quantity <= 0
                    return RateSelectionResult(
                        rate_item_id=item.id,
                        rate_mapping_id=mapping.id,
                        selection_source="user_override",
                        selection_confidence=1.0,
                        operation_code=effective_operation,
                        suggested_operation_code=suggested_operation,
                        taxonomy_code=taxonomy_code,
                        object_scope_code=object_scope_code,
                        rate_context_code=mapping.rate_context_code or selected_context,
                        rate_auto_applicable=True,
                        unit_code=item.unit_code,
                        labor_min=override.labor_hours_per_norm,
                        labor_max=override.labor_hours_per_norm,
                        labor_avg=override.labor_hours_per_norm,
                        labor_basis="user_override",
                        norm_base_quantity=item.norm_base_quantity or 1.0,
                        source_rate_id=item.source_rate_id,
                        rate_value_mode=item.rate_value_mode,
                        resolution_status="resolved_by_user_override",
                        requires_user_input=False,
                        user_override_id=override.id,
                        user_override_scope="user",
                        user_override_owner_id=override.user_id,
                        applicability_hash=override.applicability_hash,
                        applicability_json=normalize_applicability(effective_applicability),
                        needs_review=quantity_missing,
                        review_reason="quantity_missing" if quantity_missing else None,
                        candidates=placeholder_candidates,
                    )
            item, mapping, _source, _factor = placeholders[0]
            return RateSelectionResult(
                rate_item_id=item.id,
                rate_mapping_id=mapping.id,
                selection_source="user_defined_on_first_use",
                selection_confidence=mapping.confidence,
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                rate_context_code=mapping.rate_context_code or selected_context,
                rate_auto_applicable=False,
                unit_code=item.unit_code,
                norm_base_quantity=item.norm_base_quantity or 1.0,
                source_rate_id=item.source_rate_id,
                rate_value_mode=item.rate_value_mode,
                resolution_status="requires_user_input",
                requires_user_input=True,
                applicability_hash=canonical_applicability_hash(effective_applicability),
                applicability_json=normalize_applicability(effective_applicability),
                needs_review=True,
                review_reason="user_rate_input_required" if user_id else "user_rate_identity_required",
                candidates=placeholder_candidates,
            )

        ranked: list[tuple[int, float, WorkRateItem, WorkRateMapping, float]] = []
        provisional: list[tuple[int, float, WorkRateItem, WorkRateMapping, float]] = []
        for item, mapping, source, factor in compatible:
            priority = self._source_priority(source)
            if source.source_kind == SOURCE_OBSERVATION and item.approved_as_rate:
                priority = 450
            row = (priority, mapping.confidence, item, mapping, factor)
            if item.resolution_status == "requires_manual_approval" and not item.auto_applicable:
                provisional.append(row)
            else:
                ranked.append(row)
        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        provisional.sort(key=lambda row: (row[0], row[1]), reverse=True)

        if not ranked and provisional:
            _priority, confidence, item, mapping, factor = provisional[0]
            return RateSelectionResult(
                rate_item_id=item.id,
                rate_mapping_id=mapping.id,
                selection_source="provisional_catalog_candidate",
                selection_confidence=confidence,
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                rate_context_code=mapping.rate_context_code or selected_context,
                rate_auto_applicable=False,
                unit_code=item.unit_code,
                labor_min=item.labor_min,
                labor_max=item.labor_max,
                labor_avg=item.labor_avg,
                labor_basis=item.labor_basis,
                norm_base_quantity=item.norm_base_quantity or 1.0,
                source_rate_id=item.source_rate_id,
                rate_value_mode=item.rate_value_mode,
                resolution_status=item.resolution_status,
                needs_review=True,
                review_reason="provisional_rate_requires_approval",
                candidates=[{
                    "rate_item_id": r[2].id, "rate_mapping_id": r[3].id,
                    "source_rate_id": r[2].source_rate_id, "name": r[2].name,
                    "unit_code": r[2].unit_code, "norm_base_quantity": r[2].norm_base_quantity,
                    "rate_context_code": r[3].rate_context_code,
                    "labor_avg": r[2].labor_avg, "confidence": r[1],
                    "conversion_factor": r[4],
                } for r in provisional[:10]],
            )

        if not ranked:
            reason = (
                "facade_cladding_rate_not_available"
                if effective_operation == "facade_cladding"
                else "no_approved_compatible_rate"
            )
            return RateSelectionResult(
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                rate_context_code=selected_context,
                unit_code=unit_code,
                needs_review=True,
                review_reason=reason,
                rate_auto_applicable=False,
            )

        top_priority, top_confidence, top_item, top_mapping, conversion = ranked[0]
        equivalent = [
            row for row in ranked
            if row[0] == top_priority and abs(row[1] - top_confidence) < 0.02
        ]
        candidate_rows = list(ranked[:10])
        for row in provisional:
            if len(candidate_rows) >= 10:
                break
            candidate_rows.append(row)
        candidates = [
            {
                "rate_item_id": item.id,
                "rate_mapping_id": mapping.id,
                "source_id": item.source_id,
                "source_rate_id": item.source_rate_id,
                "name": item.name,
                "unit_code": item.unit_code,
                "norm_base_quantity": item.norm_base_quantity,
                "rate_context_code": mapping.rate_context_code,
                "price_avg": item.price_avg,
                "labor_avg": item.labor_avg,
                "confidence": confidence,
                "conversion_factor": factor,
            }
            for _, confidence, item, mapping, factor in candidate_rows
        ]
        if len(equivalent) > 1:
            return RateSelectionResult(
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                rate_context_code=selected_context,
                unit_code=unit_code,
                needs_review=True,
                review_reason="multiple_equivalent_rate_candidates",
                rate_auto_applicable=False,
                candidates=candidates,
            )

        source = source_by_id[top_item.source_id]
        selection_source = "project_specific" if (
            source.source_kind == SOURCE_MANUAL
            or (source.source_kind == SOURCE_OBSERVATION and top_item.approved_as_rate)
        ) else source.source_kind
        quantity_missing = quantity is None or quantity <= 0
        return RateSelectionResult(
            rate_item_id=top_item.id,
            rate_mapping_id=top_mapping.id,
            selection_source=selection_source,
            selection_confidence=top_confidence,
            operation_code=effective_operation,
            suggested_operation_code=suggested_operation,
            taxonomy_code=taxonomy_code,
            object_scope_code=object_scope_code,
            rate_context_code=top_mapping.rate_context_code or selected_context,
            rate_auto_applicable=True,
            unit_code=top_item.unit_code,
            price_min=top_item.price_min,
            price_max=top_item.price_max,
            price_avg=top_item.price_avg,
            labor_min=top_item.labor_min,
            labor_max=top_item.labor_max,
            labor_avg=top_item.labor_avg,
            labor_basis=top_item.labor_basis,
            norm_base_quantity=top_item.norm_base_quantity or 1.0,
            source_rate_id=top_item.source_rate_id,
            rate_value_mode=top_item.rate_value_mode,
            resolution_status=top_item.resolution_status,
            needs_review=quantity_missing,
            review_reason="quantity_missing" if quantity_missing else None,
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
        norm_base = float(rate_item.norm_base_quantity or 1.0)
        if norm_base <= 0:
            return {"labor_min_total": None, "labor_avg_total": None, "labor_max_total": None, "needs_review": "invalid_norm_base_quantity"}
        norm_count = rate_quantity / norm_base
        return {
            "labor_min_total": round(norm_count * rate_item.labor_min, 4) if rate_item.labor_min is not None else None,
            "labor_avg_total": round(norm_count * rate_item.labor_avg, 4) if rate_item.labor_avg is not None else None,
            "labor_max_total": round(norm_count * rate_item.labor_max, 4) if rate_item.labor_max is not None else None,
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
        subtype_output_per_day: float | None = None,
        quantity: float | None = None,
        crew_size: int | None = None,
        hours_per_day: float = 8.0,
    ) -> LaborResolution:
        if manual_labor_hours is not None and manual_labor_hours > 0:
            return LaborResolution(manual_labor_hours, "manual")

        fallback_hours: float | None = None
        if subtype_output_per_day and subtype_output_per_day > 0 and quantity and quantity > 0 and crew_size and crew_size > 0:
            days = math.ceil(quantity / subtype_output_per_day)
            fallback_hours = float(days * crew_size * hours_per_day)

        sources: list[tuple[str, float | None]]
        if labor_source_mode == "manual":
            return LaborResolution(None, None, True, "manual_labor_required")
        if labor_source_mode == "rate_catalog":
            sources = [
                ("project_specific_rate", project_specific_labor_hours),
                ("catalog_independent", catalog_independent_labor_hours),
                ("catalog_derived", catalog_derived_labor_hours),
                ("subtype_output_per_day", fallback_hours),
            ]
        elif labor_source_mode == "fer":
            sources = [
                ("fer", fer_labor_hours),
                ("subtype_output_per_day", fallback_hours),
            ]
        elif labor_source_mode == "hybrid":
            sources = [
                ("project_specific_rate", project_specific_labor_hours),
                ("catalog_independent", catalog_independent_labor_hours),
                ("fer", fer_labor_hours),
                ("catalog_derived", catalog_derived_labor_hours),
                ("subtype_output_per_day", fallback_hours),
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
