"""Rate selection, labour calculations and package-conflict detection."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from app.services.gantt_calculations import calculate_working_days
from app.services.work_context_rules import (
    build_rate_context_text,
    has_any,
    resolve_masonry_context,
    resolve_insulation_context,
    resolve_membrane_context,
    resolve_roof_covering_context,
    resolve_roof_structure_context,
    resolve_special_masonry_operation,
)
from app.services.work_rate_import_service import normalize_name
from app.services.user_work_rate_service import (
    UserWorkRateRecord,
    build_work_rate_key,
    find_compatible_user_rate,
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
    def _inferred_item_applicability(item: WorkRateItem, mapping: WorkRateMapping | None = None) -> dict[str, str]:
        text = normalize_name(" ".join(
            value
            for value in (
                item.name,
                item.normalized_name,
                item.notes,
                item.normalized_notes,
            )
            if value
        ))
        inferred: dict[str, str] = {}
        if has_any(text, ("металлочерепиц", "металлическ черепиц")):
            inferred.setdefault("roof_covering_material", "metal_tile")
            inferred.setdefault("base_type", "sparse_batten")
        elif has_any(text, ("гибк черепиц", "битумн черепиц", "мягк черепиц", "мягк кровл")):
            inferred.setdefault("roof_covering_material", "flexible_shingles")
            inferred.setdefault("base_type", "solid_deck")

        if has_any(text, ("минват", "минераловат", "каменн ват", "базальтов")):
            inferred.setdefault("insulation_material", "mineral_wool")
        elif has_any(text, ("эппс", "xps", "экструдирован")):
            inferred.setdefault("insulation_material", "xps")
        elif has_any(text, ("пенополистирол", "ппс", "eps")):
            inferred.setdefault("insulation_material", "eps")
        elif has_any(text, ("ппу", "пенополиуретан")):
            inferred.setdefault("insulation_material", "polyurethane_foam")
        if has_any(text, ("фасад", "наружн стен", "кирпичн стен")):
            inferred.setdefault("insulation_location", "facade")
        elif has_any(text, ("цокол", "фундамент", "подземн стен")):
            inferred.setdefault("insulation_location", "foundation_wall")
        elif has_any(text, ("под плит", "под фундаментн", "под ушп")):
            inferred.setdefault("insulation_location", "under_slab")
        elif has_any(text, ("кровл", "стропил", "чердак", "мансард")):
            inferred.setdefault("insulation_location", "roof")
        elif has_any(text, ("внутренн стен", "изнутри", "со стороны помещения")):
            inferred.setdefault("insulation_location", "internal_wall")

        if has_any(text, ("лстк", "легк стальн", "тонкостенн")):
            inferred.setdefault("roof_structure_material", "light_gauge_steel")
        elif has_any(text, ("дерев", "пиломат", "брус", "дос")):
            inferred.setdefault("roof_structure_material", "timber")
        elif has_any(text, ("клеен", "glulam")):
            inferred.setdefault("roof_structure_material", "glulam")

        has_vapor = has_any(text, ("пароизоляц", "пароизоляцион"))
        has_wind_waterproof = has_any(text, ("гидроветр", "ветрозащит", "ветро", "диффузион", "мембран"))
        if has_vapor and has_wind_waterproof:
            inferred.setdefault("membrane_type", "combined_membrane")
        elif has_vapor:
            inferred.setdefault("membrane_type", "vapor_barrier")
        elif has_wind_waterproof:
            inferred.setdefault("membrane_type", "wind_waterproof_membrane")
        if has_any(text, ("со стороны помещения", "внутренн")):
            inferred.setdefault("installation_position", "interior_side")
        elif has_any(text, ("кровл", "скатн", "чердак", "мансард", "стропил")):
            inferred.setdefault("installation_position", "roof_assembly")
        elif has_any(text, ("наружн", "снаружи")):
            inferred.setdefault("installation_position", "exterior_side")

        if mapping and mapping.rate_context_code:
            inferred.setdefault("rate_context_code", mapping.rate_context_code)
        return inferred

    @classmethod
    def _item_applicability(cls, item: WorkRateItem, mapping: WorkRateMapping | None = None) -> dict[str, Any]:
        expected = dict(item.applicability_json or (item.source_payload or {}).get("applicability") or {})
        inferred = cls._inferred_item_applicability(item, mapping)
        operation_code = mapping.operation_code if mapping else None
        operation_fields = {
            "thermal_insulation": {"insulation_location", "insulation_material"},
            "roof_structure_installation": {"roof_structure_material"},
            "roof_covering_installation": {"roof_covering_material", "base_type"},
            "membrane_installation": {"membrane_type", "installation_position"},
            "wind_membrane_installation": {"membrane_type", "installation_position"},
        }
        contextual_fields = {
            "insulation_location",
            "insulation_material",
            "roof_structure_material",
            "roof_covering_material",
            "base_type",
            "membrane_type",
            "installation_position",
        }
        allowed_contextual = operation_fields.get(operation_code, set())
        for key, value in inferred.items():
            if key in contextual_fields and key not in allowed_contextual:
                continue
            expected.setdefault(key, value)
        return expected

    @staticmethod
    def _item_applicability_matches(
        item: WorkRateItem,
        actual: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
    ) -> bool:
        expected = expected or item.applicability_json or (item.source_payload or {}).get("applicability") or {}
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
        for expected_key in (
            "roof_covering_material",
            "base_type",
            "insulation_location",
            "insulation_material",
            "roof_structure_material",
            "membrane_type",
            "installation_position",
        ):
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
    def _user_rate_result(
        *,
        user_rate: UserWorkRateRecord,
        quantity: float | None,
        operation_code: str,
        suggested_operation_code: str | None,
        taxonomy_code: str,
        object_scope_code: str | None,
        rate_context_code: str | None,
        rate_variant_code: str | None,
    ) -> RateSelectionResult:
        labor = float(user_rate.labor_hours_per_unit)
        quantity_missing = quantity is None or quantity <= 0
        return RateSelectionResult(
            status="resolved",
            rate_source="user_catalog",
            rate_item_id=None,
            rate_mapping_id=None,
            selection_source="user_catalog",
            selection_confidence=1.0,
            operation_code=operation_code,
            suggested_operation_code=suggested_operation_code,
            taxonomy_code=taxonomy_code,
            object_scope_code=object_scope_code,
            rate_context_code=rate_context_code,
            rate_variant_code=rate_variant_code,
            rate_auto_applicable=True,
            unit_code=user_rate.unit_code,
            labor_min=labor,
            labor_max=labor,
            labor_avg=labor,
            labor_basis="user_catalog",
            norm_base_quantity=1.0,
            resolution_status="resolved_by_user_catalog",
            requires_user_input=False,
            user_rate_id=user_rate.id,
            user_rate_owner_id=user_rate.user_id,
            needs_review=quantity_missing,
            review_reason="quantity_missing" if quantity_missing else None,
        )

    def _user_fallback(
        self,
        *,
        user_id: str | None,
        user_rates: Iterable[UserWorkRateRecord] | None,
        taxonomy_code: str,
        operation_code: str,
        object_scope_code: str | None,
        rate_context_code: str | None,
        rate_variant_code: str | None,
        unit_code: str | None,
        quantity: float | None,
        suggested_operation_code: str | None,
        candidates: list[dict[str, Any]] | None = None,
        original_reason: str | None = None,
        original_sub_reason: str | None = None,
    ) -> RateSelectionResult:
        if operation_code in self.operation_packages:
            return RateSelectionResult(
                status="needs_decomposition",
                rate_source=None,
                operation_code=operation_code,
                suggested_operation_code=suggested_operation_code,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                rate_context_code=rate_context_code,
                rate_variant_code=rate_variant_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason="atomic_work_required",
                review_sub_reason="package_expansion_required",
                rate_auto_applicable=False,
                candidates=list(candidates or []),
            )
        if unit_code:
            key = build_work_rate_key(
                taxonomy_code=taxonomy_code,
                operation_code=operation_code,
                object_scope_code=object_scope_code,
                rate_context_code=rate_context_code,
                rate_variant_code=rate_variant_code,
                unit_code=unit_code,
            )
            user_rate = find_compatible_user_rate(
                rows=user_rates,
                user_id=user_id,
                key=key,
            )
            if user_rate is not None:
                return self._user_rate_result(
                    user_rate=user_rate,
                    quantity=quantity,
                    operation_code=operation_code,
                    suggested_operation_code=suggested_operation_code,
                    taxonomy_code=taxonomy_code,
                    object_scope_code=object_scope_code,
                    rate_context_code=rate_context_code,
                    rate_variant_code=rate_variant_code,
                )
        return RateSelectionResult(
            status="needs_user_rate",
            rate_source=None,
            selection_source=None,
            operation_code=operation_code,
            suggested_operation_code=suggested_operation_code,
            taxonomy_code=taxonomy_code,
            object_scope_code=object_scope_code,
            rate_context_code=rate_context_code,
            rate_variant_code=rate_variant_code,
            unit_code=unit_code,
            rate_auto_applicable=False,
            resolution_status="needs_user_rate",
            requires_user_input=True,
            needs_review=True,
            review_reason="user_rate_input_required",
            review_sub_reason=original_sub_reason or original_reason or "rate_not_found_for_unit",
            candidates=list(candidates or []),
        )

    def select_rate(
        self,
        *,
        taxonomy_code: str,
        operation_code: str,
        object_scope_code: str | None,
        rate_context_code: str | None = None,
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
        user_rates: Iterable[UserWorkRateRecord] | None = None,
        applicability: dict[str, Any] | None = None,
    ) -> RateSelectionResult:
        """Resolve a rate in the strict order global -> user -> request."""
        work_text, section_context_text, source_context_text = build_rate_context_text(
            work_name=work_name,
            item_text=item_text,
            spec=spec,
            section_title=section_title,
            section_description=section_description,
            section_parent_context=section_parent_context,
        )
        taxonomy_code = str(taxonomy_code or "").strip()
        operation_code = str(operation_code or "").strip()
        object_scope_code = str(object_scope_code or "").strip() or None
        unit_code = str(unit_code or "").strip() or None
        if not taxonomy_code or taxonomy_code == "unknown/needs_review":
            return RateSelectionResult(
                status="needs_clarification",
                taxonomy_code=taxonomy_code or None,
                operation_code=operation_code or None,
                object_scope_code=object_scope_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason="work_classification_required",
            )
        if not operation_code:
            return RateSelectionResult(
                status="needs_clarification",
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason="work_operation_required",
            )
        if not unit_code:
            return RateSelectionResult(
                status="needs_clarification",
                taxonomy_code=taxonomy_code,
                operation_code=operation_code,
                object_scope_code=object_scope_code,
                needs_review=True,
                review_reason="work_unit_required",
            )

        special_operation = resolve_special_masonry_operation(work_text, section_context_text)
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
                    status="needs_clarification",
                    operation_code=operation_code,
                    suggested_operation_code=special_operation,
                    taxonomy_code=taxonomy_code,
                    object_scope_code=object_scope_code,
                    unit_code=unit_code,
                    needs_review=True,
                    review_reason="special_masonry_operation_mismatch",
                )
            effective_operation = special_operation

        effective_applicability = dict(applicability or {})
        selected_context = (
            str(rate_context_code or "").strip()
            or str(effective_applicability.get("rate_context_code") or "").strip()
            or None
        )
        context_result = None
        rate_variant_code: str | None = None
        missing_variant_fields: list[str] = []
        variant_review_reason: str | None = None
        if effective_operation == "brick_masonry":
            if selected_context is None:
                context_result = resolve_masonry_context(source_context_text)
        elif effective_operation == "roof_covering_installation":
            if selected_context is None:
                context_result = resolve_roof_covering_context(source_context_text)
        elif effective_operation == "thermal_insulation":
            context_result = resolve_insulation_context(source_context_text)
        elif effective_operation == "roof_structure_installation":
            context_result = resolve_roof_structure_context(source_context_text)
        elif effective_operation in {"membrane_installation", "wind_membrane_installation"}:
            context_result = resolve_membrane_context(source_context_text)
        elif effective_operation == "facade_cladding":
            selected_context = "facade"
        elif effective_operation == "arm_belt_masonry":
            selected_context = "brick_arm_belt"

        if context_result is not None:
            key_context_operation = effective_operation in {
                "brick_masonry",
                "roof_covering_installation",
            }
            if key_context_operation and context_result.context_code:
                selected_context = context_result.context_code
                effective_applicability["rate_context_code"] = selected_context
            elif context_result.context_code:
                # Stable canonical discriminator for personal rates. Unlike the
                # full applicability blob, this contains only operation-specific
                # material/location semantics and is reusable across projects,
                # floors and stages.
                rate_variant_code = context_result.context_code
            for key, value in (context_result.applicability or {}).items():
                effective_applicability.setdefault(key, value)

            variant_requirements = {
                "thermal_insulation": ("insulation_location", "insulation_material"),
                "roof_structure_installation": ("roof_structure_material",),
                "membrane_installation": ("membrane_type", "installation_position"),
                "wind_membrane_installation": ("membrane_type", "installation_position"),
            }
            required_variant_fields = variant_requirements.get(effective_operation, ())
            missing_variant_fields = [
                field_name
                for field_name in required_variant_fields
                if not effective_applicability.get(field_name)
            ]
            variant_review_reason = context_result.review_reason or "rate_variant_required"
            if key_context_operation and context_result.needs_review:
                return RateSelectionResult(
                    status="needs_clarification",
                    operation_code=effective_operation,
                    suggested_operation_code=suggested_operation,
                    taxonomy_code=taxonomy_code,
                    object_scope_code=object_scope_code,
                    rate_context_code=None,
                    rate_variant_code=rate_variant_code,
                    unit_code=unit_code,
                    needs_review=True,
                    review_reason=context_result.review_reason or "rate_context_required",
                )

        item_rows = [item for item in items if item.is_active]
        item_by_id = {item.id: item for item in item_rows}
        source_by_id = {source.id: source for source in sources if source.is_active}
        mapping_rows = [mapping for mapping in mappings if mapping.is_active]

        relevant_scope_mappings = [
            mapping
            for mapping in mapping_rows
            if mapping.mapping_mode not in {MAPPING_EXCLUDED, MAPPING_UNMAPPED}
            and mapping.operation_code == effective_operation
            and (not mapping.taxonomy_code or mapping.taxonomy_code == taxonomy_code)
        ]
        # Scope is mandatory only when every relevant canonical mapping is
        # scope-specific. A mixture of generic and scoped mappings must not
        # block a valid generic personal norm.
        scope_is_required = bool(effective_applicability.get("object_scope_required")) or (
            bool(relevant_scope_mappings) and all(
                mapping.object_scope_code is not None
                for mapping in relevant_scope_mappings
            )
        )
        if scope_is_required and object_scope_code is None:
            return RateSelectionResult(
                status="needs_clarification",
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=None,
                rate_context_code=selected_context,
                rate_variant_code=rate_variant_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason="object_scope_required",
            )

        global_candidates: list[tuple[int, float, WorkRateItem, WorkRateMapping, WorkRateSource]] = []
        rejected_candidates: list[dict[str, Any]] = []
        for mapping in mapping_rows:
            if mapping.mapping_mode in {MAPPING_EXCLUDED, MAPPING_UNMAPPED}:
                continue
            if mapping.operation_code != effective_operation:
                continue
            if mapping.taxonomy_code and mapping.taxonomy_code != taxonomy_code:
                continue
            # The reusable key is exact. Generic NULL and a concrete value are
            # different scopes/contexts and must not silently substitute each other.
            if mapping.object_scope_code != object_scope_code:
                continue
            if mapping.rate_context_code != selected_context:
                continue
            item = item_by_id.get(mapping.rate_item_id)
            if item is None or not item.has_active_mapping:
                continue
            source = source_by_id.get(item.source_id)
            if source is None:
                continue
            if source.source_kind == SOURCE_OBSERVATION and not item.approved_as_rate:
                continue
            if item.rate_value_mode == "user_defined_on_first_use":
                continue
            if not item.auto_applicable:
                continue
            if item.unit_code != unit_code:
                rejected_candidates.append({
                    "rate_item_id": item.id,
                    "rate_mapping_id": mapping.id,
                    "name": item.name,
                    "unit_code": item.unit_code,
                    "labor_avg": item.labor_avg,
                    "rejected_reason": "unit_incompatible",
                })
                continue
            if item.labor_avg is None:
                continue
            item_applicability = self._item_applicability(item, mapping)
            if not self._item_applicability_matches(item, effective_applicability, item_applicability):
                rejected_candidates.append({
                    "rate_item_id": item.id,
                    "rate_mapping_id": mapping.id,
                    "name": item.name,
                    "unit_code": item.unit_code,
                    "labor_avg": item.labor_avg,
                    "rejected_reason": "applicability_mismatch",
                })
                continue
            priority = self._source_priority(source)
            if source.source_kind == SOURCE_OBSERVATION and item.approved_as_rate:
                priority = 450
            global_candidates.append((priority, mapping.confidence, item, mapping, source))

        if global_candidates:
            global_candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
            _priority, confidence, item, mapping, source = global_candidates[0]
            quantity_missing = quantity is None or quantity <= 0
            selection_source = "project_specific" if (
                source.source_kind == SOURCE_MANUAL
                or (source.source_kind == SOURCE_OBSERVATION and item.approved_as_rate)
            ) else source.source_kind
            return RateSelectionResult(
                status="resolved",
                rate_source="global_catalog",
                rate_item_id=item.id,
                rate_mapping_id=mapping.id,
                selection_source=selection_source,
                selection_confidence=confidence,
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                rate_context_code=selected_context,
                rate_variant_code=rate_variant_code,
                rate_auto_applicable=True,
                unit_code=item.unit_code,
                price_min=item.price_min,
                price_max=item.price_max,
                price_avg=item.price_avg,
                labor_min=item.labor_min,
                labor_max=item.labor_max,
                labor_avg=item.labor_avg,
                labor_basis=item.labor_basis,
                norm_base_quantity=item.norm_base_quantity or 1.0,
                source_rate_id=item.source_rate_id,
                rate_value_mode=item.rate_value_mode,
                resolution_status="resolved_by_global_catalog",
                needs_review=quantity_missing,
                review_reason="quantity_missing" if quantity_missing else None,
                candidates=[
                    {
                        "rate_item_id": candidate_item.id,
                        "rate_mapping_id": candidate_mapping.id,
                        "source_id": candidate_item.source_id,
                        "source_rate_id": candidate_item.source_rate_id,
                        "name": candidate_item.name,
                        "unit_code": candidate_item.unit_code,
                        "norm_base_quantity": candidate_item.norm_base_quantity,
                        "rate_context_code": candidate_mapping.rate_context_code,
                        "labor_avg": candidate_item.labor_avg,
                        "confidence": candidate_confidence,
                    }
                    for _, candidate_confidence, candidate_item, candidate_mapping, _ in global_candidates[:10]
                ],
            )

        if missing_variant_fields:
            return RateSelectionResult(
                status="needs_clarification",
                operation_code=effective_operation,
                suggested_operation_code=suggested_operation,
                taxonomy_code=taxonomy_code,
                object_scope_code=object_scope_code,
                rate_context_code=selected_context,
                rate_variant_code=rate_variant_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason=variant_review_reason or "rate_variant_required",
                review_sub_reason=",".join(missing_variant_fields),
            )

        original_reason = "unit_incompatible" if any(
            row.get("rejected_reason") == "unit_incompatible"
            for row in rejected_candidates
        ) else "no_approved_compatible_rate"
        return self._user_fallback(
            user_id=user_id,
            user_rates=user_rates,
            taxonomy_code=taxonomy_code,
            operation_code=effective_operation,
            object_scope_code=object_scope_code,
            rate_context_code=selected_context,
            rate_variant_code=rate_variant_code,
            unit_code=unit_code,
            quantity=quantity,
            suggested_operation_code=suggested_operation,
            candidates=rejected_candidates[:10],
            original_reason=original_reason,
            original_sub_reason=(
                "quantity_conversion_required"
                if original_reason == "unit_incompatible"
                else "atomic_rate_missing"
            ),
        )

    @staticmethod
    def calculate_labor(
        *,
        quantity: float | None,
        quantity_unit: str | None,
        rate_item: WorkRateItem,
        unit_conversion_factor_override: float | None = None,
    ) -> dict[str, float | None | str]:
        if quantity is None or quantity <= 0:
            return {
                "labor_min_total": None,
                "labor_avg_total": None,
                "labor_max_total": None,
                "needs_review": "quantity_missing",
            }
        factor = unit_conversion_factor_override
        if factor is None:
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
        return calculate_working_days(labor_hours, crew_size, hours_per_day)

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
        if (
            subtype_output_per_day
            and subtype_output_per_day > 0
            and quantity
            and quantity > 0
            and crew_size
            and crew_size > 0
            and hours_per_day > 0
        ):
            # Labour is continuous. Only duration is rounded to whole working
            # days by calculate_working_days()/calculate_duration().
            fallback_hours = float(
                quantity / subtype_output_per_day * crew_size * hours_per_day
            )

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
