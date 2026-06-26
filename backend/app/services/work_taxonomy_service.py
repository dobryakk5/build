"""Work taxonomy classification, hierarchy and precedence helpers.

``construction_work_dictionary_v6_4_14.json`` is the canonical work
classifier. The CSV helper remains only for legacy callers.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.work_context_rules import (
    build_rate_context_text,
    has_internal_wall_insulation_exception,
    resolve_special_masonry_operation,
)
from app.models import WorkPrecedence, WorkSubtype


DICTIONARY_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "construction_work_dictionary_v6_4_14.json"
)
DICTIONARY_SOURCE = "construction_work_dictionary_v6_4_14"
PROMPT_VERSION = "estimate-v6.4.14"
UNKNOWN_SUBTYPE_CODE = "unknown/needs_review"
UNKNOWN_SUBTYPE_NAME = "Требует ручной классификации"
SERVICE_ROW_SUBTYPE_NAME = "Служебная строка сметы"
LEGACY_ESTIMATE_KIND_BY_TYPE_ID: dict[str, int] = {
    "site_earthworks": 1,
    "residential_construction": 2,
    "commercial_construction": 3,
    "nonresidential_reconstruction": 4,
    "residential_renovation": 5,
    "commercial_renovation": 6,
    "internal_mep": 7,
    "external_mep": 8,
    "landscape_hardscape": 9,
}


@dataclass(frozen=True)
class SubtypeDef:
    macro_id: int
    code: str
    name: str
    keywords: tuple[str, ...]
    section_code: str | None = None
    section_name: str | None = None
    terms_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class PrecedenceEdge:
    predecessor_code: str
    successor_code: str
    lag_days: int


@dataclass(frozen=True)
class SubtypeMatch:
    macro_id: int
    code: str
    name: str
    score: int
    section_code: str | None = None
    section_name: str | None = None
    confidence: str | None = None
    needs_review: bool = False


@dataclass(frozen=True)
class ClassificationCandidate:
    rank: int
    stage: str
    section_code: str | None
    section_name: str | None
    subtype_code: str | None = None
    subtype_name: str | None = None
    score: int = 0
    section_score: int | None = None
    subtype_score: int | None = None
    delta_to_next: int | None = None
    confidence: str = "low"
    needs_review: bool = False
    source: str = "rule_based"
    matched_terms: dict[str, list[str]] = field(default_factory=dict)
    related_sections: list[str] = field(default_factory=list)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "stage": self.stage,
            "section_code": self.section_code,
            "section_name": self.section_name,
            "subtype_code": self.subtype_code,
            "subtype_name": self.subtype_name,
            "score": self.score,
            "section_score": self.section_score,
            "subtype_score": self.subtype_score,
            "delta_to_next": self.delta_to_next,
            "confidence": self.confidence,
            "needs_review": self.needs_review,
            "source": self.source,
            "matched_terms": self.matched_terms,
            "related_sections": self.related_sections,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OperationDetectionCandidate:
    code: str | None
    kind: str
    score: float
    matched_terms: tuple[str, ...] = ()
    source: str = "dictionary_operation_terms"
    stage_numbers: tuple[str, ...] = ()
    stage_option_ids: tuple[str, ...] = ()
    target_codes: tuple[str, ...] = ()
    exact: bool = False
    context_gate_matched: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "kind": self.kind,
            "score": round(float(self.score), 4),
            "matched_terms": list(self.matched_terms),
            "source": self.source,
            "stage_numbers": list(self.stage_numbers),
            "stage_option_ids": list(self.stage_option_ids),
            "target_codes": list(self.target_codes),
            "exact": self.exact,
            "context_gate_matched": self.context_gate_matched,
        }


@dataclass(frozen=True)
class OperationDetectionResult:
    operation_code: str | None
    operation_package_code: str | None
    confidence_score: float | None
    matched_terms: tuple[str, ...]
    candidates: tuple[OperationDetectionCandidate, ...] = ()
    needs_review: bool = False
    reason: str | None = None
    preferred_stage_number: str | None = None
    preferred_stage_option_id: str | None = None
    multi_operation_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassificationResult:
    section_code: str | None
    section_name: str | None
    subtype_code: str
    subtype_name: str
    score: int
    confidence: str
    needs_review: bool
    source: str
    matched_terms: dict[str, list[str]]
    candidates: list[ClassificationCandidate]
    related_sections: list[str]
    reason: str
    dictionary_version: str
    row_role: str = "work"
    parent_context_source: str | None = None
    parent_context_code: str | None = None
    context_inherited: bool = False
    context_inheritance_reason: str | None = None
    classification_scope: str = "global"
    scope_estimate_type_id: str | None = None
    scope_project_variant_id: str | None = None
    scope_candidate_sections: int = 0
    scope_candidate_pairs: int = 0
    fallback_used: bool = False
    scoped_rejection_reason: str | None = None
    scoped_candidate_subtype: str | None = None
    global_candidate_subtype: str | None = None
    global_fallback_accept_reason: str | None = None
    object_priority_rule: str | None = None
    object_conflicts: tuple[str, ...] = ()
    operation_code: str | None = None
    operation_package_code: str | None = None
    operation_confidence_score: float | None = None
    operation_candidates: tuple[dict[str, Any], ...] = ()
    operation_detection_reason: str | None = None
    operation_needs_review: bool = False
    operation_multi_codes: tuple[str, ...] = ()
    preferred_stage_option_id: str | None = None
    section_object_candidates: tuple[dict[str, Any], ...] = ()
    selected_object_scope_code: str | None = None
    object_scope_confidence_score: float | None = None
    object_scope_source: str | None = None
    context_override_blocked: bool = False
    context_override_reason: str | None = None
    preferred_stage_number: str | None = None
    suggested_taxonomy_code: str | None = None
    suggested_operation_code: str | None = None

    def as_raw_data(self) -> dict[str, Any]:
        return {
            "work_section_code": self.section_code,
            "work_section_name": self.section_name,
            "work_subtype_code": self.subtype_code,
            "work_subtype_name": self.subtype_name,
            "classification_score": self.score,
            "classification_confidence": self.confidence,
            "classification_needs_review": self.needs_review,
            "classification_source": self.source,
            "classification_candidates": [c.as_dict() for c in self.candidates],
            "classification_matched_terms": self.matched_terms,
            "classification_reason": self.reason,
            "classification_related_sections": self.related_sections,
            "dictionary_version": self.dictionary_version,
            "row_role": self.row_role,
            "parent_context_source": self.parent_context_source,
            "parent_context_code": self.parent_context_code,
            "context_inherited": self.context_inherited,
            "context_inheritance_reason": self.context_inheritance_reason,
            "classification_scope": self.classification_scope,
            "classification_scope_estimate_type": self.scope_estimate_type_id,
            "classification_scope_project_variant": self.scope_project_variant_id,
            "classification_scope_candidate_sections": self.scope_candidate_sections,
            "classification_scope_candidate_pairs": self.scope_candidate_pairs,
            "classification_fallback_used": self.fallback_used,
            "scoped_rejection_reason": self.scoped_rejection_reason,
            "scoped_candidate_subtype": self.scoped_candidate_subtype,
            "global_candidate_subtype": self.global_candidate_subtype,
            "global_fallback_accept_reason": self.global_fallback_accept_reason,
            "object_priority_rule": self.object_priority_rule,
            "object_conflicts": list(self.object_conflicts),
            "operation_code": self.operation_code,
            "operation_package_code": self.operation_package_code,
            "operation_confidence_score": self.operation_confidence_score,
            "operation_candidates": [dict(item) for item in self.operation_candidates],
            "operation_detection_reason": self.operation_detection_reason,
            "operation_needs_review": self.operation_needs_review,
            "operation_multi_codes": list(self.operation_multi_codes),
            "preferred_stage_option_id": self.preferred_stage_option_id,
            "section_object_candidates": [dict(item) for item in self.section_object_candidates],
            "selected_object_scope_code": self.selected_object_scope_code,
            "object_scope_confidence_score": self.object_scope_confidence_score,
            "object_scope_source": self.object_scope_source,
            "context_override_blocked": self.context_override_blocked,
            "context_override_reason": self.context_override_reason,
            "preferred_stage_number": self.preferred_stage_number,
            "classification_review_reason": self.reason if self.needs_review else None,
            "suggested_taxonomy_code": self.suggested_taxonomy_code,
            "suggested_operation_code": self.suggested_operation_code,
            # Legacy names kept until the UI/API is fully migrated.
            "subtype_code": self.subtype_code,
            "subtype_name": self.subtype_name,
            "macro_id": None,
        }


@dataclass(frozen=True)
class TaxonomyScope:
    """Precomputed work-type scope for one estimate type or project variant."""

    estimate_type_id: str
    project_variant_id: str | None
    allowed_sections: frozenset[str]
    allowed_pairs: frozenset[tuple[str, str]]
    stages: tuple[dict[str, Any], ...]
    name: str
    scope_source: str = "stage_options"




_taxonomy_cache: list[SubtypeDef] | None = None
_precedence_cache: list[PrecedenceEdge] | None = None


def clear_cache() -> None:
    """Reset DB-backed caches. Used by tests."""
    global _taxonomy_cache, _precedence_cache
    _taxonomy_cache = None
    _precedence_cache = None
    _load_dictionary.cache_clear()
    cached_variant_catalog = globals().get("_variant_operation_alias_catalog")
    if cached_variant_catalog is not None and hasattr(cached_variant_catalog, "cache_clear"):
        cached_variant_catalog.cache_clear()
    for cached in ("_term_signature", "_boundary_pattern", "_cached_stems"):
        func = globals().get(cached)
        if func is not None and hasattr(func, "cache_clear"):
            func.cache_clear()


@lru_cache(maxsize=1)
def _load_dictionary() -> dict[str, Any]:
    with open(DICTIONARY_FILE, encoding="utf-8") as fh:
        payload = json.load(fh)
    validate_dictionary_payload(payload)
    return payload


def _effective_project_variant(variant: dict[str, Any]) -> dict[str, Any]:
    """Return the project variant embedded in the canonical dictionary.

    Since v6.4.14 source-variant files are audit/build inputs only. Runtime
    must not overlay the canonical dictionary with a second JSON source.
    """
    return variant


def validate_dictionary_payload(payload: dict[str, Any]) -> None:
    required_top_level = (
        "sections",
        "project_hierarchy",
        "project_hierarchy_schema",
        "mapping_generation_policy",
        "sequential_scoring_policy",
    )
    missing = [key for key in required_top_level if not payload.get(key)]
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if not meta.get("dictionary_version") and not payload.get("dictionary_version"):
        missing.append("meta.dictionary_version")
    hierarchy = payload.get("project_hierarchy") if isinstance(payload.get("project_hierarchy"), dict) else {}
    if not hierarchy.get("canonical_stages"):
        missing.append("project_hierarchy.canonical_stages")
    if missing:
        raise RuntimeError("Runtime work dictionary is missing required blocks: " + ", ".join(missing))

    sections_by_id = {
        str(section.get("id") or "")
        for section in payload.get("sections") or []
        if isinstance(section, dict)
    }
    subtypes_by_section: set[tuple[str, str]] = set()
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or "")
        for subtype in section.get("subtypes") or []:
            if isinstance(subtype, dict):
                subtypes_by_section.add((section_id, str(subtype.get("id") or "")))

    canonical_stages = hierarchy.get("canonical_stages") or {}
    canonical_stage_ids = (
        set(canonical_stages)
        if isinstance(canonical_stages, dict)
        else {str(item.get("id") or "") for item in canonical_stages if isinstance(item, dict)}
    )
    errors: list[str] = []
    for estimate_type in hierarchy.get("estimate_types") or []:
        if not isinstance(estimate_type, dict):
            continue
        type_number = str(estimate_type.get("number") or "")
        for variant in estimate_type.get("project_variants") or []:
            if not isinstance(variant, dict):
                continue
            variant_number = str(variant.get("number") or "")
            if type_number and not variant_number.startswith(type_number + "."):
                errors.append(f"variant number mismatch: {variant_number}")
            occurrence_seen: dict[str, set[int]] = {}
            for stage in variant.get("stages") or []:
                if not isinstance(stage, dict):
                    continue
                for key in (
                    "number",
                    "title",
                    "canonical_stage_id",
                    "primary_work_type",
                    "related_work_types",
                    "stage_role",
                    "autofill_enabled",
                    "stage_options",
                    "stage_options_mode",
                    "detail_lines",
                    "occurrence_index",
                    "occurrence_label",
                ):
                    if key not in stage:
                        errors.append(f"stage {stage.get('number')} missing {key}")
                stage_number = str(stage.get("number") or "")
                if variant_number and not stage_number.startswith(variant_number + "."):
                    errors.append(f"stage number mismatch: {stage_number}")
                canonical_stage_id = str(stage.get("canonical_stage_id") or "")
                if canonical_stage_id not in canonical_stage_ids:
                    errors.append(f"stage {stage_number} has invalid canonical_stage_id {canonical_stage_id}")
                occurrence_index = stage.get("occurrence_index")
                if isinstance(occurrence_index, int) and canonical_stage_id:
                    seen = occurrence_seen.setdefault(canonical_stage_id, set())
                    if occurrence_index in seen:
                        errors.append(f"stage {stage_number} duplicate occurrence_index {occurrence_index}")
                    seen.add(occurrence_index)
                primary = stage.get("primary_work_type") if isinstance(stage.get("primary_work_type"), dict) else {}
                if stage.get("autofill_enabled") and not (
                    primary.get("section_id") and primary.get("subtype_id")
                ):
                    errors.append(f"stage {stage_number} autofill_enabled without primary_work_type subtype")
                stage_options = stage.get("stage_options") or []
                if stage.get("stage_options_mode") == "grouped_all" and not stage_options:
                    errors.append(
                        f"stage {stage_number} has stage_options_mode=grouped_all without stage_options"
                    )
                if stage.get("stage_options_mode") == "grouped_all" and stage.get("autofill_enabled"):
                    errors.append(f"stage {stage_number} grouped parent must have autofill_enabled=false")
                option_ids = [
                    str(option.get("id") or option.get("number") or "")
                    for option in stage_options
                    if isinstance(option, dict)
                ]
                duplicate_option_ids = sorted(
                    option_id for option_id in set(option_ids) if option_id and option_ids.count(option_id) > 1
                )
                if duplicate_option_ids:
                    errors.append(
                        f"stage {stage_number} duplicate stage option ids: {', '.join(duplicate_option_ids)}"
                    )
                for ref in [primary, *(stage.get("related_work_types") or [])]:
                    if not isinstance(ref, dict):
                        continue
                    section_id = ref.get("section_id")
                    subtype_id = ref.get("subtype_id")
                    if section_id and section_id not in sections_by_id:
                        errors.append(f"stage {stage_number} invalid section_id {section_id}")
                    if section_id and subtype_id and (str(section_id), str(subtype_id)) not in subtypes_by_section:
                        errors.append(f"stage {stage_number} invalid subtype {section_id}/{subtype_id}")
                for option in stage.get("stage_options") or []:
                    if not isinstance(option, dict):
                        continue
                    has_taxonomy_target = bool(option.get("section_id") and option.get("subtype_id"))
                    has_operation_target = bool(option.get("operation_codes") or option.get("package_codes"))
                    if option.get("autofill_enabled") and not (has_taxonomy_target or has_operation_target):
                        errors.append(
                            f"stage {stage_number} option {option.get('id')} autofill without taxonomy or operation target"
                        )
                    section_id = option.get("section_id")
                    subtype_id = option.get("subtype_id")
                    if section_id and subtype_id and (str(section_id), str(subtype_id)) not in subtypes_by_section:
                        errors.append(f"stage {stage_number} option {option.get('id')} invalid subtype {section_id}/{subtype_id}")

    operation_policy = payload.get("operation_object_resolution_policy")
    if isinstance(operation_policy, dict):
        operations = operation_policy.get("operations") or {}
        metadata = operation_policy.get("operation_metadata") or {}
        packages = operation_policy.get("operation_packages") or {}
        if not isinstance(operations, dict):
            errors.append("operation policy operations must be dict")
            operations = {}
        if not isinstance(metadata, dict):
            errors.append("operation policy operation_metadata must be dict")
            metadata = {}
        if not isinstance(packages, dict):
            errors.append("operation policy operation_packages must be dict")
            packages = {}
        for operation_code in operations:
            if operation_code not in metadata:
                errors.append(f"operation {operation_code} missing metadata")
        for package_code, package in packages.items():
            if package_code not in operations:
                errors.append(f"package {package_code} missing operation terms")
                continue
            package_meta = metadata.get(package_code) or {}
            if package_meta.get("kind") != "package":
                errors.append(f"package {package_code} metadata kind must be package")
            for atomic_code in (package or {}).get("included_operations") or []:
                if atomic_code not in operations:
                    errors.append(f"package {package_code} has missing component {atomic_code}")
                    continue
                atomic_meta = metadata.get(atomic_code) or {}
                if atomic_meta.get("kind") != "atomic":
                    errors.append(f"package {package_code} component {atomic_code} must be atomic")
        for raw_rule in operation_policy.get("rules") or []:
            if not isinstance(raw_rule, dict):
                continue
            operation_code = raw_rule.get("operation_code") or raw_rule.get("operation")
            if operation_code and operation_code not in operations:
                errors.append(f"operation rule references unknown operation {operation_code}")
    if errors:
        raise RuntimeError("Runtime work dictionary failed validation gates: " + "; ".join(errors[:20]))


def dictionary_version(payload: dict[str, Any] | None = None) -> str:
    payload = payload or _load_dictionary()
    meta = payload.get("meta") or {}
    explicit = payload.get("dictionary_version") or meta.get("dictionary_version")
    if explicit:
        return str(explicit)
    schema_version = meta.get("schema_version") or "unknown"
    return f"{DICTIONARY_SOURCE}@{schema_version}"


def _project_hierarchy(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or _load_dictionary()
    hierarchy = payload.get("project_hierarchy")
    return hierarchy if isinstance(hierarchy, dict) else {}


def _hierarchy_estimate_types(payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    hierarchy = _project_hierarchy(payload)
    types = hierarchy.get("estimate_types")
    return types if isinstance(types, list) else []


def assert_project_hierarchy_compatible(payload: dict[str, Any] | None = None) -> None:
    """Fail fast if runtime hierarchy cannot support legacy estimate_kind mapping."""
    type_ids = {str(item.get("id") or "") for item in _hierarchy_estimate_types(payload)}
    missing = sorted(set(LEGACY_ESTIMATE_KIND_BY_TYPE_ID) - type_ids)
    if missing:
        raise RuntimeError(
            "Runtime work dictionary is missing estimate_type ids: "
            + ", ".join(missing)
        )


def legacy_estimate_kind_for_type(estimate_type_id: str) -> int:
    try:
        return LEGACY_ESTIMATE_KIND_BY_TYPE_ID[estimate_type_id]
    except KeyError:
        raise ValueError(f"Unknown estimate_type_id: {estimate_type_id}") from None


def _public_work_stage(stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(stage.get("id") or ""),
        "number": str(stage.get("number") or ""),
        "title": str(stage.get("title") or ""),
        "canonical_stage_id": stage.get("canonical_stage_id") or None,
        "stage_instance_id": stage.get("stage_instance_id"),
        "template_stage_number": stage.get("template_stage_number"),
        "legacy_stage_number": stage.get("legacy_stage_number"),
        "floor_number": stage.get("floor_number"),
        "floor_kind": stage.get("floor_kind"),
        "floor_label": stage.get("floor_label"),
        "floor_component": stage.get("floor_component"),
        "component_role": stage.get("component_role"),
        "sort_order": stage.get("sort_order"),
        "floor_binding": stage.get("floor_binding") or None,
        "stage_kind": stage.get("stage_kind"),
        "stage_role": stage.get("stage_role"),
        "stage_options_mode": stage.get("stage_options_mode") or "none",
        "stage_options": stage.get("stage_options") or [],
        "detail_lines": stage.get("detail_lines") or [],
        "operations": stage.get("operations") or [],
        "operation_packages": stage.get("operation_packages") or [],
        "primary_operation_code": stage.get("primary_operation_code"),
        "occurrence_index": stage.get("occurrence_index"),
        "occurrence_label": stage.get("occurrence_label"),
        "autofill_enabled": bool(stage.get("autofill_enabled", stage.get("autofill_enabled_default", False))),
        "primary_work_type": stage.get("primary_work_type") or None,
        "related_work_types": stage.get("related_work_types") or [],
    }


def _public_project_variant(variant: dict[str, Any], include_stages: bool) -> dict[str, Any]:
    variant = _effective_project_variant(variant)
    stages = variant.get("stages") if isinstance(variant.get("stages"), list) else []
    item = {
        "id": str(variant.get("id") or ""),
        "number": str(variant.get("number") or ""),
        "title": str(variant.get("title") or ""),
        "stages_count": len(stages),
        "building_params_schema": deepcopy(variant.get("building_params_schema") or {}),
        "floor_structure_schema": deepcopy(variant.get("floor_structure_schema") or {}),
    }
    if include_stages:
        item["stages"] = [_public_work_stage(stage) for stage in stages]
    return item


def get_project_hierarchy(
    *,
    dictionary_version_filter: str | None = None,
    include_stages: bool = False,
) -> dict[str, Any]:
    payload = _load_dictionary()
    current_version = dictionary_version(payload)
    if dictionary_version_filter and dictionary_version_filter != current_version:
        raise ValueError(f"Unsupported dictionary_version: {dictionary_version_filter}")
    assert_project_hierarchy_compatible(payload)
    return {
        "dictionary_version": current_version,
        "estimate_types": [
            {
                "id": str(item.get("id") or ""),
                "number": str(item.get("number") or ""),
                "title": str(item.get("title") or ""),
                "estimate_kind": legacy_estimate_kind_for_type(str(item.get("id") or "")),
                "estimate_profile_id": str(item.get("estimate_profile_id") or item.get("id") or ""),
                "project_variants": [
                    _public_project_variant(variant, include_stages)
                    for variant in (item.get("project_variants") or [])
                    if isinstance(variant, dict)
                ],
            }
            for item in _hierarchy_estimate_types(payload)
        ],
    }


def get_estimate_types() -> list[dict[str, Any]]:
    payload = _load_dictionary()
    assert_project_hierarchy_compatible(payload)
    return [
        {
            "number": str(item.get("number") or ""),
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or ""),
            "estimate_kind": legacy_estimate_kind_for_type(str(item.get("id") or "")),
            "estimate_profile_id": str(item.get("estimate_profile_id") or item.get("id") or ""),
        }
        for item in _hierarchy_estimate_types(payload)
    ]


def _find_estimate_type(payload: dict[str, Any], estimate_type_id: str) -> dict[str, Any]:
    for estimate_type in _hierarchy_estimate_types(payload):
        if str(estimate_type.get("id") or "") == estimate_type_id or str(estimate_type.get("number") or "") == estimate_type_id:
            return estimate_type
    raise ValueError(f"Unknown estimate_type_id: {estimate_type_id}")


def _find_project_variant(estimate_type: dict[str, Any], project_variant_id: str) -> dict[str, Any]:
    for variant in estimate_type.get("project_variants") or []:
        if str(variant.get("id") or "") == project_variant_id or str(variant.get("number") or "") == project_variant_id:
            return variant
    raise ValueError("project_variant_id does not belong to estimate_type_id")


def get_project_variants(estimate_type_id: str) -> list[dict[str, Any]]:
    payload = _load_dictionary()
    estimate_type = _find_estimate_type(payload, estimate_type_id)
    return [
        _public_project_variant(variant, include_stages=False)
        for variant in estimate_type.get("project_variants") or []
        if isinstance(variant, dict)
    ]


def get_project_variant_stages(estimate_type_id: str, project_variant_id: str) -> list[dict[str, Any]]:
    payload = _load_dictionary()
    estimate_type = _find_estimate_type(payload, estimate_type_id)
    variant = _effective_project_variant(_find_project_variant(estimate_type, project_variant_id))
    return [
        _public_work_stage(stage)
        for stage in variant.get("stages") or []
        if isinstance(stage, dict)
    ]


def get_project_variant_definition(estimate_type_id: str, project_variant_id: str) -> dict[str, Any]:
    payload = _load_dictionary()
    estimate_type = _find_estimate_type(payload, str(estimate_type_id))
    return deepcopy(_effective_project_variant(_find_project_variant(estimate_type, str(project_variant_id))))


def validate_project_variant_building_params(
    estimate_type_id: str,
    project_variant_id: str,
    building_params: dict[str, Any] | None,
):
    from app.services.floor_structure_service import validate_building_params

    variant = get_project_variant_definition(estimate_type_id, project_variant_id)
    return validate_building_params(building_params, variant)


def get_project_variant_stage_instances(
    estimate_type_id: str,
    project_variant_id: str,
    building_params: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    from app.services.floor_structure_service import build_stage_instances, validate_building_params

    variant = get_project_variant_definition(estimate_type_id, project_variant_id)
    params = validate_building_params(building_params, variant)
    return [
        _public_work_stage(stage)
        for stage in build_stage_instances(variant, params)
    ]


def _scope_pairs_from_stages(stages: list[dict[str, Any]]) -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for stage in stages:
        refs: list[dict[str, Any]] = []
        primary = stage.get("primary_work_type")
        if isinstance(primary, dict):
            refs.append(primary)
        refs.extend(ref for ref in (stage.get("related_work_types") or []) if isinstance(ref, dict))
        refs.extend(ref for ref in (stage.get("stage_options") or []) if isinstance(ref, dict))
        for ref in refs:
            section_id = str(ref.get("section_id") or "").strip()
            subtype_id = str(ref.get("subtype_id") or "").strip()
            if section_id and subtype_id:
                pairs.add((section_id, subtype_id))
    return frozenset(pairs)


def get_variant_scope(estimate_type_id: str, project_variant_id: str) -> TaxonomyScope:
    payload = _load_dictionary()
    estimate_type = _find_estimate_type(payload, str(estimate_type_id))
    variant = _effective_project_variant(_find_project_variant(estimate_type, str(project_variant_id)))
    stages = [
        _public_work_stage(stage)
        for stage in variant.get("stages") or []
        if isinstance(stage, dict)
    ]
    pairs = _scope_pairs_from_stages(stages)
    if not pairs:
        raise RuntimeError(
            f"Taxonomy scope is empty for {estimate_type_id}/{project_variant_id}; "
            "check project_hierarchy mappings"
        )
    pair_sections = frozenset(section_id for section_id, _ in pairs)
    explicit_categories = frozenset(
        str(value).strip()
        for value in (variant.get("allowed_categories") or [])
        if str(value).strip()
    )
    if explicit_categories:
        allowed_sections = pair_sections & explicit_categories
        scope_source = "allowed_categories"
    else:
        allowed_sections = pair_sections
        scope_source = "stage_options"
    if not allowed_sections:
        raise RuntimeError(
            f"Taxonomy category scope is empty for {estimate_type_id}/{project_variant_id}; "
            "allowed_categories must intersect stage work-type pairs"
        )
    scoped_pairs = frozenset(pair for pair in pairs if pair[0] in allowed_sections)
    return TaxonomyScope(
        estimate_type_id=str(estimate_type_id),
        project_variant_id=str(project_variant_id),
        allowed_sections=allowed_sections,
        allowed_pairs=scoped_pairs,
        stages=tuple(stages),
        name="variant_scope",
        scope_source=scope_source,
    )


def get_estimate_type_scope(estimate_type_id: str) -> TaxonomyScope:
    payload = _load_dictionary()
    estimate_type = _find_estimate_type(payload, estimate_type_id)
    stages: list[dict[str, Any]] = []
    for variant in estimate_type.get("project_variants") or []:
        if not isinstance(variant, dict):
            continue
        stages.extend(
            _public_work_stage(stage)
            for stage in variant.get("stages") or []
            if isinstance(stage, dict)
        )
    pairs = _scope_pairs_from_stages(stages)
    if not pairs:
        raise RuntimeError(f"Taxonomy scope is empty for estimate type {estimate_type_id}")
    return TaxonomyScope(
        estimate_type_id=str(estimate_type_id),
        project_variant_id=None,
        allowed_sections=frozenset(section_id for section_id, _ in pairs),
        allowed_pairs=pairs,
        stages=tuple(stages),
        name="estimate_type_scope",
    )


def _write_dictionary(payload: dict[str, Any]) -> None:
    tmp_path = DICTIONARY_FILE.with_suffix(DICTIONARY_FILE.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp_path.replace(DICTIONARY_FILE)


def update_project_stage_title(stage_id: str, title: str) -> dict[str, Any]:
    new_title = title.strip()
    if not new_title:
        raise ValueError("Stage title cannot be empty")
    if len(new_title) > 240:
        raise ValueError("Stage title is too long")

    payload = deepcopy(_load_dictionary())
    matched_stage: dict[str, Any] | None = None
    matched_count = 0
    for estimate_type in _hierarchy_estimate_types(payload):
        for variant in estimate_type.get("project_variants") or []:
            if not isinstance(variant, dict):
                continue
            for stage in variant.get("stages") or []:
                if not isinstance(stage, dict):
                    continue
                if str(stage.get("id") or "") == stage_id:
                    matched_stage = stage
                    matched_count += 1

    if matched_count == 0:
        raise KeyError(stage_id)
    if matched_count > 1:
        raise ValueError(f"Stage id is not unique: {stage_id}")

    assert matched_stage is not None
    matched_stage["title"] = new_title
    validate_dictionary_payload(payload)
    _write_dictionary(payload)
    clear_cache()
    return _public_work_stage(matched_stage)


def _estimate_categories_from_texts(texts: list[str]) -> set[str]:
    """Detect broad estimate categories once per distinct source phrase."""
    categories: set[str] = set()
    unique = {normalize_text(text) for text in texts if normalize_text(text)}
    for text in unique:
        if re.search(r"\b(?:полы?|пола|напольн\w*|стяжк\w*|линоле\w*|ламинат\w*|паркет\w*|плинтус\w*)", text):
            categories.add("floors")
        if re.search(r"\b(?:стен\w*|перегород\w*|гкл|гипсокартон)", text):
            categories.add("walls_partitions")
        if re.search(r"\bпотол\w*", text):
            categories.add("ceilings")
        if re.search(r"\b(?:окон\w*|двер\w*|витраж\w*|наличник\w*|добор\w*)", text):
            categories.add("windows_doors")
        if re.search(r"\b(?:сантех\w*|водоснабж\w*|канализац\w*|унитаз\w*|смесител\w*|раковин\w*|душев\w*|поддон\w*|труб\w*\s+ppr)", text):
            categories.add("plumbing")
        if re.search(r"\b(?:электромонтаж\w*|электрическ\w*|светильник\w*|кабел\w*|провод\w*|розет\w*|выключател\w*|автоматическ\w*\s+выключател\w*)", text):
            categories.add("electrical")
        if re.search(r"\b(?:доставк\w*|разгрузк\w*|погрузк\w*|вывоз\w*\s+мусор\w*|вынос\w*\s+мусор\w*|контейнер\w*\s+для\s+мусор\w*)", text):
            categories.add("logistics_cleanup")
    return categories


def _stage_option_category(option: dict[str, Any], stage: dict[str, Any]) -> str | None:
    explicit = option.get("category") or option.get("estimate_category")
    if explicit:
        return str(explicit)
    number = str(stage.get("number") or "")
    title = normalize_text(" ".join((str(stage.get("title") or ""), str(option.get("title") or ""))))
    section_id = str(option.get("section_id") or "")
    subtype_id = str(option.get("subtype_id") or "")
    if number in {"6.2.6", "6.2.13"} or section_id == "floor_screed" or subtype_id in {"floor_coverings", "sports_floor_finishes", "polymer_floors"}:
        return "floors"
    if number in {"6.2.4", "6.2.5", "6.2.14"} or section_id == "partitions":
        return "walls_partitions"
    if number == "6.2.7" or "потол" in title:
        return "ceilings"
    if number in {"6.2.15", "6.2.17"} or section_id == "windows_doors":
        return "windows_doors"
    if number in {"6.2.9", "6.2.11", "6.2.12"} or (section_id == "mep_internal" and subtype_id in {"water_supply", "sewage", "sanitary_fixtures", "heating"}):
        return "plumbing"
    if number in {"6.2.8", "6.2.16", "6.2.18"} or (section_id == "mep_internal" and subtype_id in {"electrical", "commissioning"}):
        return "electrical"
    if number == "6.2.19" or (section_id == "mobilization" and subtype_id == "logistics_cleanup"):
        return "logistics_cleanup"
    return None


def _variant_allowed_categories(variant: dict[str, Any]) -> tuple[set[str], str]:
    """Resolve scope from explicit metadata, otherwise only from stage_options."""
    explicit = variant.get("allowed_categories")
    if isinstance(explicit, list) and any(str(value or "").strip() for value in explicit):
        return {str(value).strip() for value in explicit if str(value or "").strip()}, "allowed_categories"
    inferred: set[str] = set()
    for stage in variant.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for option in stage.get("stage_options") or []:
            if not isinstance(option, dict):
                continue
            category = _stage_option_category(option, stage)
            if category:
                inferred.add(category)
    return inferred, "stage_options"


def suggest_project_hierarchy_variants(
    texts: list[str],
    *,
    estimate_type_id: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Suggest hierarchy variants using deduplicated terms and category coverage."""
    payload = _load_dictionary()
    unique_texts = list(dict.fromkeys(normalize_text(text) for text in texts if normalize_text(text)))
    haystack = " ".join(unique_texts[:200])
    hay_tokens = haystack.split()
    matched_categories = _estimate_categories_from_texts(unique_texts)
    estimate_types = _hierarchy_estimate_types(payload)
    type_scores: list[tuple[int, dict[str, Any], list[str]]] = []
    variant_scores: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]] = []

    def semantic_terms(values: list[Any]) -> list[str]:
        result: list[str] = []
        for value in values:
            term = str(value or "").strip()
            normalized = normalize_text(term)
            if not normalized or not re.search(r"[a-zа-яё]", normalized, re.IGNORECASE):
                continue
            if len(normalized) < 4 and len(normalized.split()) == 1:
                continue
            result.append(term)
        return result

    hay_token_set = set(hay_tokens)
    hay_stem_set = set(_cached_stems(tuple(hay_tokens)))

    def fast_match_terms(terms: list[str]) -> list[str]:
        """Suggestion matching without repeatedly scanning the full haystack."""
        matched: list[str] = []
        seen: set[str] = set()
        for raw in terms:
            term = str(raw or "").strip()
            normalized, tokens = _term_signature(term)
            if not normalized or normalized in seen:
                continue
            if normalized in haystack:
                seen.add(normalized)
                matched.append(term)
                continue
            token_matches = 0
            significant = [token for token in tokens if len(token) >= 4]
            for token in significant:
                if token in hay_token_set or _stem(token) in hay_stem_set:
                    token_matches += 1
            required = max(1, len(significant))
            if significant and token_matches >= required:
                seen.add(normalized)
                matched.append(term)
        return matched

    for estimate_type in estimate_types:
        best_variant_score = 0
        best_matches: list[str] = []
        type_title_terms = semantic_terms([estimate_type.get("title")])
        for variant in estimate_type.get("project_variants") or []:
            if not isinstance(variant, dict):
                continue
            variant_terms = semantic_terms([estimate_type.get("title"), variant.get("title")])
            for stage in variant.get("stages") or []:
                if not isinstance(stage, dict):
                    continue
                variant_terms.extend(semantic_terms([stage.get("title")]))
                variant_terms.extend(semantic_terms(list(stage.get("detail_lines") or [])))
                for option in stage.get("stage_options") or []:
                    if isinstance(option, dict):
                        variant_terms.extend(semantic_terms([option.get("title")]))
            matches = fast_match_terms(variant_terms)
            unique_matches = list(dict.fromkeys(normalize_text(term) for term in matches if normalize_text(term)))
            unique_term_score = len(unique_matches)
            allowed_categories, scope_source = _variant_allowed_categories(variant)
            covered = matched_categories & allowed_categories if allowed_categories else set()
            foreign = matched_categories - allowed_categories if allowed_categories else set()
            coverage_score = 4 * len(covered)
            complex_boost = 0
            if str(variant.get("number") or "") == "6.2":
                finish_categories = {"floors", "walls_partitions", "ceilings", "windows_doors"}
                engineering_categories = {"plumbing", "electrical"}
                if len(matched_categories & finish_categories) >= 3 and matched_categories & engineering_categories:
                    complex_boost = 10
            scope_penalty = 5 * min(len(foreign), 4)
            final_score = unique_term_score + coverage_score + complex_boost - scope_penalty
            diagnostics = {
                "unique_matched_terms": unique_matches[:20],
                "matched_categories": sorted(matched_categories),
                "allowed_categories": sorted(allowed_categories),
                "scope_source": scope_source,
                "covered_categories": sorted(covered),
                "foreign_categories": sorted(foreign),
                "unique_term_score": unique_term_score,
                "category_coverage_score": coverage_score,
                "complex_renovation_boost": complex_boost,
                "scope_mismatch_penalty": scope_penalty,
                "final_score": final_score,
            }
            variant_scores.append((final_score, estimate_type, variant, diagnostics))
            if final_score > best_variant_score:
                best_variant_score = final_score
                best_matches = unique_matches[:10]
        type_matches = fast_match_terms(type_title_terms)
        type_scores.append((best_variant_score + len(type_matches) * 3, estimate_type, best_matches or type_matches[:10]))

    type_scores.sort(key=lambda item: item[0], reverse=True)
    if estimate_type_id:
        variant_scores = [item for item in variant_scores if str(item[1].get("id") or "") == str(estimate_type_id)]
    variant_scores.sort(key=lambda item: item[0], reverse=True)
    return {
        "estimate_types": [
            {
                "id": str(item.get("id") or ""), "number": str(item.get("number") or ""),
                "title": str(item.get("title") or ""),
                "estimate_kind": legacy_estimate_kind_for_type(str(item.get("id") or "")),
                "score": score, "matched_terms": matches,
            }
            for score, item, matches in type_scores[:limit]
        ],
        "project_variants": [
            {
                "estimate_type_id": str(estimate_type.get("id") or ""),
                "estimate_type_number": str(estimate_type.get("number") or ""),
                "estimate_type_title": str(estimate_type.get("title") or ""),
                "id": str(variant.get("id") or ""), "number": str(variant.get("number") or ""),
                "title": str(variant.get("title") or ""),
                "stages_count": len(variant.get("stages") or []),
                "score": score, "matched_terms": diagnostics["unique_matched_terms"],
                **diagnostics,
            }
            for score, estimate_type, variant, diagnostics in variant_scores[:limit]
        ],
    }


def get_canonical_stages() -> dict[str, Any]:
    payload = _load_dictionary()
    hierarchy = _project_hierarchy(payload)
    canonical_stages = hierarchy.get("canonical_stages")
    return canonical_stages if isinstance(canonical_stages, dict) else {}


def get_sequential_scoring_policy() -> dict[str, Any]:
    payload = _load_dictionary()
    policy = payload.get("sequential_scoring_policy")
    return policy if isinstance(policy, dict) else {}


def get_operation_registry() -> dict[str, Any]:
    """Return the additive operation registry used by rate mapping services."""
    policy = _operation_resolution_policy()
    return {
        "version": policy.get("version"),
        "operations": deepcopy(policy.get("operations") or {}),
        "operation_metadata": deepcopy(policy.get("operation_metadata") or {}),
        "operation_packages": deepcopy(policy.get("operation_packages") or {}),
        "objects": deepcopy(policy.get("objects") or {}),
        "rules": deepcopy(policy.get("rules") or []),
    }


def validate_taxonomy_code(code: str | None) -> bool:
    if not code or "/" not in str(code):
        return False
    section_id, subtype_id = str(code).split("/", 1)
    payload = _load_dictionary()
    for section in payload.get("sections") or []:
        if not isinstance(section, dict) or str(section.get("id") or "") != section_id:
            continue
        return any(
            isinstance(subtype, dict) and str(subtype.get("id") or "") == subtype_id
            for subtype in section.get("subtypes") or []
        )
    return False


def get_subtype_context(code: str) -> dict[str, Any] | None:
    if not validate_taxonomy_code(code):
        return None
    section_id, subtype_id = code.split("/", 1)
    payload = _load_dictionary()
    for section in payload.get("sections") or []:
        if not isinstance(section, dict) or str(section.get("id") or "") != section_id:
            continue
        for subtype in section.get("subtypes") or []:
            if isinstance(subtype, dict) and str(subtype.get("id") or "") == subtype_id:
                return {
                    "taxonomy_code": code,
                    "section_id": section_id,
                    "section_title": section.get("title"),
                    "subtype_id": subtype_id,
                    "subtype_title": subtype.get("title"),
                    "terms": deepcopy(subtype.get("terms") or {}),
                    "dictionary_version": dictionary_version(payload),
                }
    return None


def get_operation_object_candidates(
    operation_code: str,
    object_scope_code: str | None = None,
) -> list[dict[str, Any]]:
    policy = _operation_resolution_policy()
    candidates: list[dict[str, Any]] = []
    for raw_rule in policy.get("rules") or []:
        if not isinstance(raw_rule, dict):
            continue
        rule_operation = raw_rule.get("operation_code") or raw_rule.get("operation")
        rule_object = raw_rule.get("object_scope_code") or raw_rule.get("object")
        if rule_operation != operation_code:
            continue
        if object_scope_code and rule_object != object_scope_code:
            continue
        section_id = raw_rule.get("section_id")
        subtype_id = raw_rule.get("subtype_id")
        candidates.append({
            "operation_code": rule_operation,
            "object_scope_code": rule_object,
            "section_id": section_id,
            "subtype_id": subtype_id,
            "taxonomy_code": f"{section_id}/{subtype_id}" if section_id and subtype_id else None,
            "preferred_stage_number": raw_rule.get("preferred_stage_number"),
        })
    return candidates


def validate_project_hierarchy_selection(
    estimate_type_id: str | None,
    project_variant_id: str | None,
) -> dict[str, Any]:
    if not estimate_type_id or not project_variant_id:
        raise ValueError("estimate_type_id and project_variant_id are required")
    payload = _load_dictionary()
    assert_project_hierarchy_compatible(payload)
    estimate_type = _find_estimate_type(payload, estimate_type_id)
    variant = _find_project_variant(estimate_type, project_variant_id)
    resolved_type_id = str(estimate_type.get("id") or "")
    resolved_variant_id = str(variant.get("id") or "")
    return {
        "estimate_kind": legacy_estimate_kind_for_type(resolved_type_id),
        "estimate_type_id": resolved_type_id,
        "estimate_type_title": estimate_type.get("title"),
        "estimate_type_number": estimate_type.get("number"),
        "project_variant_id": resolved_variant_id,
        "project_variant_title": variant.get("title"),
        "project_variant_number": variant.get("number"),
        "taxonomy_dictionary_version": dictionary_version(payload),
    }


async def load_taxonomy(db: AsyncSession) -> list[SubtypeDef]:
    global _taxonomy_cache
    if _taxonomy_cache is None:
        rows = list(
            await db.scalars(
                select(WorkSubtype).where(
                    WorkSubtype.dictionary_source.in_(
                        (DICTIONARY_SOURCE, "system")
                    )
                )
            )
        )
        if not rows:
            rows = list(await db.scalars(select(WorkSubtype)))
        _taxonomy_cache = [
            SubtypeDef(
                macro_id=r.macro_id,
                code=r.code,
                name=r.name,
                keywords=tuple(
                    k.casefold()
                    for k in (r.keywords or [])
                    if k and str(k).strip()
                ),
                section_code=r.section_code,
                section_name=r.section_name,
                terms_json=r.terms_json,
            )
            for r in rows
        ]
    return _taxonomy_cache


async def load_precedence(db: AsyncSession) -> list[PrecedenceEdge]:
    global _precedence_cache
    if _precedence_cache is None:
        rows = list(await db.scalars(select(WorkPrecedence)))
        _precedence_cache = [
            PrecedenceEdge(
                predecessor_code=r.predecessor_code,
                successor_code=r.successor_code,
                lag_days=int(r.lag_days or 0),
            )
            for r in rows
        ]
    return _precedence_cache


def _legacy_csv_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return []


def _terms_json(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _term_summary(terms_json: dict[str, Any]) -> dict[str, int]:
    subtype = terms_json.get("subtype") if isinstance(terms_json.get("subtype"), dict) else {}
    return {
        "strong_terms": len(subtype.get("strong_terms") or []),
        "weak_terms": len(subtype.get("weak_terms") or []),
        "action_object_pairs": len(subtype.get("action_object_pairs") or []),
        "negative_terms": len(subtype.get("negative_terms") or []),
    }


def _flatten_term_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_flatten_term_values(item))
        return values
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_flatten_term_values(item))
        return values
    return []


def _section_examples(subtypes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for subtype in subtypes[:4]:
        examples.append(
            {
                "work_subtype_code": subtype["work_subtype_code"],
                "work_subtype_name": subtype["work_subtype_name"],
                "taxonomy_code": subtype.get("taxonomy_code"),
                "display_code": subtype.get("display_code"),
            }
        )
    return examples


def _taxonomy_code_map(payload: dict[str, Any] | None = None) -> dict[str, str]:
    payload = payload or _load_dictionary()
    codes: dict[str, str] = {}
    for section_index, section in enumerate(payload.get("sections") or [], start=1):
        section_code = str(section["id"])
        for subtype_index, subtype in enumerate(section.get("subtypes") or [], start=1):
            codes[f"{section_code}/{subtype['id']}"] = f"{section_index}.{subtype_index}"
    return codes


def _section_taxonomy_code_map(payload: dict[str, Any] | None = None) -> dict[str, str]:
    payload = payload or _load_dictionary()
    return {
        str(section["id"]): str(section_index)
        for section_index, section in enumerate(payload.get("sections") or [], start=1)
    }


def taxonomy_code_for_subtype(code: str | None) -> str | None:
    if not code:
        return None
    return _taxonomy_code_map().get(str(code))


def _dictionary_subtypes_from_json() -> list[dict[str, Any]]:
    payload = _load_dictionary()
    rows: list[dict[str, Any]] = []
    for macro_id, section in enumerate(payload.get("sections") or [], start=1):
        section_code = str(section["id"])
        for subtype_index, subtype in enumerate(section.get("subtypes") or [], start=1):
            legacy_codes = _legacy_csv_codes(subtype.get("legacy_csv_codes"))
            work_subtype_code = f"{section_code}/{subtype['id']}"
            terms = {
                "section": {
                    key: section.get(key) or []
                    for key in (
                        "strong_terms",
                        "weak_terms",
                        "action_terms",
                        "object_terms",
                        "material_terms",
                        "document_terms",
                        "unit_hints",
                        "negative_terms",
                    )
                },
                "subtype": {
                    key: subtype.get(key) or []
                    for key in (
                        "strong_terms",
                        "weak_terms",
                        "action_object_pairs",
                        "negative_terms",
                    )
                },
            }
            rows.append(
                {
                    "macro_id": macro_id,
                    "section_code": section_code,
                    "section_name": section.get("title"),
                    "section_scope": section.get("scope"),
                    "work_subtype_code": work_subtype_code,
                    "work_subtype_name": subtype.get("title"),
                    "taxonomy_code": f"{macro_id}.{subtype_index}",
                    "display_code": legacy_codes[0] if legacy_codes else None,
                    "legacy_csv_codes": legacy_codes,
                    "terms_json": terms,
                    "dictionary_version": dictionary_version(payload),
                }
            )
    return rows


async def get_work_taxonomy_subtypes(
    db: AsyncSession,
    section_code: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    rows = list(
        await db.scalars(
            select(WorkSubtype)
            .where(WorkSubtype.dictionary_source == DICTIONARY_SOURCE)
            .order_by(WorkSubtype.macro_id, WorkSubtype.id)
        )
    )
    if rows:
        items = [
            {
                "macro_id": row.macro_id,
                "section_code": row.section_code,
                "section_name": row.section_name,
                "section_scope": row.section_scope,
                "work_subtype_code": row.code,
                "work_subtype_name": row.name,
                "display_code": row.display_code,
                "legacy_csv_codes": _legacy_csv_codes(row.legacy_csv_codes),
                "terms_json": _terms_json(row.terms_json),
                "dictionary_version": row.dictionary_source_version,
            }
            for row in rows
            if row.code != UNKNOWN_SUBTYPE_CODE
        ]
    else:
        items = _dictionary_subtypes_from_json()

    taxonomy_codes = _taxonomy_code_map()
    if section_code:
        items = [item for item in items if item.get("section_code") == section_code]
    needle = normalize_text(q) if q else ""
    if needle:
        items = [
            item
            for item in items
            if needle in normalize_text(
                " ".join(
                    str(part or "")
                    for part in (
                        item.get("work_subtype_code"),
                        item.get("work_subtype_name"),
                        item.get("taxonomy_code") or taxonomy_codes.get(str(item.get("work_subtype_code") or "")),
                        item.get("display_code"),
                        " ".join(item.get("legacy_csv_codes") or []),
                        " ".join(_flatten_term_values(item.get("terms_json"))),
                    )
                )
            )
        ]

    return [
        {
            "work_subtype_code": item["work_subtype_code"],
            "work_subtype_name": item["work_subtype_name"],
            "section_code": item["section_code"],
            "section_name": item["section_name"],
            "taxonomy_code": item.get("taxonomy_code") or taxonomy_codes.get(str(item["work_subtype_code"])),
            "display_code": item.get("display_code"),
            "legacy_csv_codes": item.get("legacy_csv_codes") or [],
            "term_summary": _term_summary(_terms_json(item.get("terms_json"))),
            "terms_json": _terms_json(item.get("terms_json")),
            "dictionary_version": item.get("dictionary_version"),
        }
        for item in items
    ]


async def get_work_taxonomy_sections(db: AsyncSession) -> list[dict[str, Any]]:
    subtypes = await get_work_taxonomy_subtypes(db)
    scope_by_code: dict[str, str | None] = {}
    for item in _dictionary_subtypes_from_json():
        scope_by_code.setdefault(str(item["section_code"]), item.get("section_scope"))
    taxonomy_codes = _section_taxonomy_code_map()

    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for subtype in subtypes:
        section_code = str(subtype["section_code"])
        if section_code not in grouped:
            grouped[section_code] = {
                "section_code": section_code,
                "section_name": subtype.get("section_name"),
                "taxonomy_code": taxonomy_codes.get(section_code),
                "scope": scope_by_code.get(section_code),
                "subtypes_count": 0,
                "_subtypes": [],
                "dictionary_version": subtype.get("dictionary_version"),
            }
            order.append(section_code)
        grouped[section_code]["subtypes_count"] += 1
        grouped[section_code]["_subtypes"].append(subtype)

    sections: list[dict[str, Any]] = []
    for section_code in order:
        section = grouped[section_code]
        section["examples"] = _section_examples(section.pop("_subtypes"))
        sections.append(section)
    return sections


async def build_work_section_palette(
    db: AsyncSession,
    estimates: list[Any],
) -> list[dict[str, Any]]:
    sections = await get_work_taxonomy_sections(db)
    by_code = {section["section_code"]: section for section in sections}
    primary_codes: list[str] = []
    for estimate in estimates:
        raw = estimate.raw_data if isinstance(getattr(estimate, "raw_data", None), dict) else {}
        code = getattr(estimate, "work_section_code", None) or raw.get("work_section_code")
        if code and code in by_code and code not in primary_codes:
            primary_codes.append(code)

    if not primary_codes:
        return [{**section, "is_primary": True} for section in sections]

    ordered: list[dict[str, Any]] = []
    for code in primary_codes:
        ordered.append({**by_code[code], "is_primary": True})
    for section in sections:
        if section["section_code"] not in primary_codes:
            ordered.append({**section, "is_primary": False})
    return ordered


_PUNCT_RE = re.compile(r"[^\w\s./²³-]+", re.UNICODE)
_HYPHEN_RE = re.compile(r"[-–—]+")
_SPACES_RE = re.compile(r"\s+")
_NEGATION_TOKENS = {"без", "не"}


def normalize_text(value: Any) -> str:
    text = str(value or "").casefold().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    text = _HYPHEN_RE.sub(" ", text)
    return _SPACES_RE.sub(" ", text).strip()


def _tokens(value: str) -> list[str]:
    return [t for t in normalize_text(value).split() if t]


_RU_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "его",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ый",
    "ий",
    "ой",
    "ого",
    "ых",
    "их",
    "ам",
    "ям",
    "ах",
    "ях",
    "ою",
    "ею",
    "ка",
    "ки",
    "ку",
    "ок",
    "ек",
    "а",
    "я",
    "ы",
    "и",
    "у",
    "ю",
    "ь",
    "е",
    "о",
)


def _stem(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix in _RU_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _token_skeleton(token: str) -> str:
    return re.sub(r"[аеёиоуыэюя]", "", token)


def _token_matches(term_token: str, hay_token: str, hay_stem: str) -> bool:
    token_stem = _stem(term_token)
    if (
        hay_token == term_token
        or hay_stem == token_stem
        or (len(token_stem) >= 5 and hay_token.startswith(token_stem))
        or (len(token_stem) >= 5 and len(hay_stem) >= 5 and token_stem.startswith(hay_stem))
        or (token_stem.startswith("разраб") and hay_stem.startswith("разраб"))
    ):
        return True
    if len(token_stem) >= 4 and len(hay_stem) >= 4:
        return (
            token_stem[:4] == hay_stem[:4]
            and _token_skeleton(token_stem) == _token_skeleton(hay_stem)
        )
    return False


def _matched_token_is_negated(index: int, hay_tokens: list[str]) -> bool:
    return index > 0 and hay_tokens[index - 1] in _NEGATION_TOKENS


@lru_cache(maxsize=50000)
def _term_signature(term: str) -> tuple[str, tuple[str, ...]]:
    norm_term = normalize_text(term)
    return norm_term, tuple(token for token in norm_term.split() if token)


@lru_cache(maxsize=50000)
def _boundary_pattern(norm_term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(norm_term)}(?!\w)")


@lru_cache(maxsize=10000)
def _cached_stems(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_stem(token) for token in tokens)


def _term_matches(term: str, haystack: str, hay_tokens: list[str] | None = None) -> bool:
    norm_term, term_tokens_tuple = _term_signature(str(term))
    if not norm_term:
        return False
    hay_tokens = hay_tokens or haystack.split()
    term_tokens = list(term_tokens_tuple)
    if not term_tokens:
        return False
    if len(term_tokens) > 1:
        if _boundary_pattern(norm_term).search(haystack):
            if any(
                re.search(rf"(?<!\w){negation}\s+{re.escape(norm_term)}(?!\w)", haystack)
                for negation in _NEGATION_TOKENS
            ):
                return False
            return True
    elif norm_term in hay_tokens:
        return any(
            token == norm_term and not _matched_token_is_negated(index, hay_tokens)
            for index, token in enumerate(hay_tokens)
        )
    hay_stems = _cached_stems(tuple(hay_tokens))
    for token in term_tokens:
        token_matches = [
            index
            for index, (ht, hs) in enumerate(zip(hay_tokens, hay_stems, strict=False))
            if _token_matches(token, ht, hs) and not _matched_token_is_negated(index, hay_tokens)
        ]
        if not token_matches:
            return False
    return True


def _match_terms(terms: list[str], haystack: str, hay_tokens: list[str]) -> list[str]:
    matched: list[str] = []
    seen: set[str] = set()
    for raw in terms or []:
        term = str(raw).strip()
        if not term:
            continue
        key = _term_signature(term)[0]
        if key in seen:
            continue
        if _term_matches(term, haystack, hay_tokens):
            seen.add(key)
            matched.append(term)
    return matched


def _row_role_rules(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or _load_dictionary()
    return payload.get("row_role_rules") or {}


def _matches_overhead_role(
    rules: dict[str, Any],
    haystack: str,
    hay_tokens: list[str],
    name_text: str,
) -> bool:
    """Match overhead rows without treating a mounting type as costs.

    ``накладной светильник`` and ``монтаж накладных светильников`` describe
    the physical installation method.  The standalone legacy marker
    ``накладные`` is therefore accepted only as a complete label or in an
    explicit financial phrase.
    """
    explicit_labels = {"накладные", "накладные расходы"}
    explicit_phrases = (
        "накладные расходы",
        "общехозяйственные расходы",
        "общепроизводственные расходы",
    )
    if name_text in explicit_labels or any(phrase in haystack for phrase in explicit_phrases):
        return True

    markers = [
        str(marker)
        for marker in (rules.get("overhead_markers") or [])
        if normalize_text(marker) != "накладные"
    ]
    return bool(_match_terms(markers, haystack, hay_tokens))


def classify_row_role(
    name: str | None,
    section: str | None = None,
    unit: str | None = None,
    quantity: float | int | None = None,
    payload: dict[str, Any] | None = None,
    allow_absent_header: bool = False,
) -> str:
    """Classify an estimate row role before assigning a work subtype."""
    payload = payload or _load_dictionary()
    rules = _row_role_rules(payload)
    text = " ".join(str(part) for part in (section, name, unit) if part)
    haystack = normalize_text(text)
    hay_tokens = haystack.split()
    work_text = " ".join(str(part) for part in (name, unit) if part)
    work_haystack = normalize_text(work_text)
    work_hay_tokens = work_haystack.split()
    name_text = normalize_text(name or "")
    if not name_text:
        return "unknown"

    for term in rules.get("skip_if_name_matches") or []:
        if normalize_text(term) == name_text:
            if _matches_overhead_role(rules, haystack, hay_tokens, name_text):
                return "overhead"
            if str(term).casefold() in {"смета", "сводная смета", "материалы / трудозатраты"}:
                return "header"
            return "total"

    header_rules = rules.get("header_detection") or {}
    context_rules = payload.get("context_inheritance_rules") or {}
    profile_header_terms: list[str] = []
    for profile in payload.get("estimate_profiles") or []:
        profile_header_terms.extend(profile.get("context_header_terms") or [])
    header_terms = list(context_rules.get("header_markers") or []) + profile_header_terms
    can_check_header = allow_absent_header or unit is not None or quantity is not None
    if can_check_header and header_rules.get("unit_empty_or_absent") and not str(unit or "").strip():
        empty_qty = quantity is None or quantity == 0
        if header_rules.get("quantity_empty_zero_or_absent") and empty_qty:
            if _match_terms(header_terms, name_text, name_text.split()):
                return "header"

    for role, marker_key in (
        ("overhead", "overhead_markers"),
        ("work", "work_markers"),
        ("logistics", "logistics_markers"),
        ("mechanism", "mechanism_markers"),
        ("labor", "labor_markers"),
        ("material", "material_markers"),
    ):
        role_haystack = work_haystack if role == "work" else haystack
        role_hay_tokens = work_hay_tokens if role == "work" else hay_tokens
        if role == "overhead":
            matched = _matches_overhead_role(rules, role_haystack, role_hay_tokens, name_text)
        else:
            matched = bool(_match_terms(rules.get(marker_key) or [], role_haystack, role_hay_tokens))
        if matched:
            return role

    if (
        can_check_header
        and header_rules.get("unit_empty_or_absent")
        and not str(unit or "").strip()
    ):
        empty_qty = quantity is None or quantity == 0
        short_name = len(name_text.split()) <= 6
        if (
            header_rules.get("quantity_empty_zero_or_absent")
            and empty_qty
            and header_rules.get("short_section_like_name")
            and short_name
        ):
            return "header"

    return "unknown"


def service_row_roles(payload: dict[str, Any] | None = None) -> set[str]:
    rules = _row_role_rules(payload)
    return {
        role
        for role, policy in (rules.get("classification_policy") or {}).items()
        if policy in {"do_not_create_work_subtype_unless_operator_confirms", "skip", "set_context_only"}
    }


def _apply_estimate_profiles(
    section_scores: dict[str, int],
    section_matches: dict[str, dict[str, list[str]]],
    haystack: str,
    hay_tokens: list[str],
    payload: dict[str, Any],
) -> list[str]:
    weights = (payload.get("scoring") or {}).get("weights") or {}
    boost = int(weights.get("conflict_prefer_boost", 4))
    penalty_value = int(weights.get("conflict_penalty", -4))
    applied: list[str] = []
    for profile in payload.get("estimate_profiles") or []:
        terms = _match_terms(profile.get("strong_terms") or [], haystack, hay_tokens)
        if not terms:
            continue
        profile_id = str(profile.get("id") or "estimate_profile")
        for section_id in profile.get("prefer_sections") or []:
            section_id = str(section_id)
            if section_id not in section_scores:
                continue
            section_scores[section_id] = section_scores.get(section_id, 0) + boost
            section_matches.setdefault(section_id, {}).setdefault(
                "estimate_profile_terms", []
            ).extend(terms)
            applied.append(f"{profile_id}:prefer:{section_id}")
        for section_id in profile.get("penalize_sections") or []:
            section_id = str(section_id)
            if section_id not in section_scores:
                continue
            section_scores[section_id] = section_scores.get(section_id, 0) + penalty_value
            section_matches.setdefault(section_id, {}).setdefault(
                "estimate_profile_penalty_terms", []
            ).extend(terms)
            applied.append(f"{profile_id}:penalize:{section_id}")
    return applied


def should_inherit_parent_context(
    row_role: str,
    name: str | None,
    result: ClassificationResult | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    payload = payload or _load_dictionary()
    rules = _row_role_rules(payload)
    policy = (rules.get("classification_policy") or {}).get(row_role)
    if policy in {"do_not_create_work_subtype_unless_operator_confirms", "skip", "set_context_only"}:
        return False
    context_rules = payload.get("context_inheritance_rules") or {}
    if row_role in set(rules.get("inherit_parent_for_roles") or []):
        return True
    if row_role != "work" or not context_rules.get("generic_work_rows_inherit_parent_context_if_low_delta"):
        return False
    if result and not result.needs_review:
        return False
    haystack = normalize_text(name or "")
    return bool(_match_terms(context_rules.get("generic_work_terms") or [], haystack, haystack.split()))


def inherited_context_raw(
    parent: dict[str, Any],
    *,
    row_role: str,
    reason: str,
    source: str = "nearest_work_or_group",
) -> dict[str, Any]:
    return {
        "work_section_code": parent.get("work_section_code"),
        "work_section_name": parent.get("work_section_name"),
        "work_subtype_code": parent.get("work_subtype_code") or parent.get("subtype_code"),
        "work_subtype_name": parent.get("work_subtype_name") or parent.get("subtype_name"),
        "classification_score": parent.get("classification_score"),
        "classification_confidence": parent.get("classification_confidence") or "medium",
        "classification_needs_review": False,
        "classification_source": "context_inherited",
        "classification_candidates": parent.get("classification_candidates") or [],
        "classification_matched_terms": parent.get("classification_matched_terms") or {},
        "classification_reason": reason,
        "classification_related_sections": parent.get("classification_related_sections") or [],
        "dictionary_version": parent.get("dictionary_version") or dictionary_version(),
        "subtype_code": parent.get("work_subtype_code") or parent.get("subtype_code"),
        "subtype_name": parent.get("work_subtype_name") or parent.get("subtype_name"),
        "macro_id": None,
        "row_role": row_role,
        "parent_context_source": source,
        "parent_context_code": parent.get("work_subtype_code") or parent.get("subtype_code"),
        "context_inherited": True,
        "context_inheritance_reason": reason,
    }


def _score_section(
    section: dict[str, Any],
    haystack: str,
    hay_tokens: list[str],
    weights: dict[str, int],
) -> tuple[int, dict[str, list[str]]]:
    matched: dict[str, list[str]] = {}
    score = 0

    strong = _match_terms(section.get("strong_terms") or [], haystack, hay_tokens)
    if strong:
        matched["strong_terms"] = strong
        for term in strong:
            score += (
                int(weights.get("exact_strong_phrase", 7))
                if normalize_text(term) in haystack
                else int(weights.get("strong_term", 5))
            )

    for key, weight_key in (
        ("object_terms", "object_term"),
        ("material_terms", "material_term"),
        ("action_terms", "action_term"),
        ("weak_terms", "weak_term"),
        ("document_terms", "document_term"),
        ("unit_hints", "unit_hint_boost"),
    ):
        values = _match_terms(section.get(key) or [], haystack, hay_tokens)
        if values:
            matched[key] = values
            score += len(values) * int(weights.get(weight_key, 0))

    negative = _match_terms(section.get("negative_terms") or [], haystack, hay_tokens)
    if negative:
        matched["negative_terms"] = negative
        score += len(negative) * int(weights.get("negative_term", -6))

    return score, matched


def _apply_conflict_rules(
    sections_by_id: dict[str, dict[str, Any]],
    section_scores: dict[str, int],
    section_matches: dict[str, dict[str, list[str]]],
    haystack: str,
    hay_tokens: list[str],
    payload: dict[str, Any],
) -> list[str]:
    """Apply all soft conflict rules as additive deltas.

    Earlier versions promoted a preferred section above the current maximum inside
    each rule loop. That made the final winner depend on JSON rule ordering. Here
    all applicable boosts and penalties are collected first and applied once.
    Hard intents such as demolition are resolved before this function.
    """
    weights = (payload.get("scoring") or {}).get("weights") or {}
    prefer_boost = int(weights.get("conflict_prefer_boost", 4))
    penalty_value = int(weights.get("conflict_penalty", -4))
    deltas: dict[str, int] = {section_id: 0 for section_id in sections_by_id}
    applied: list[str] = []

    for rule in payload.get("global_conflict_rules") or []:
        if_any = rule.get("if_any") or []
        if_all = rule.get("if_all") or []
        if if_any and not _match_terms(if_any, haystack, hay_tokens):
            continue
        if if_all and not all(
            _match_terms([term], haystack, hay_tokens) for term in if_all
        ):
            continue
        if not if_any and not if_all:
            continue

        rule_id = str(rule.get("id") or "conflict_rule")
        for prefer in rule.get("prefer") or []:
            section_id = str(prefer.get("section_id") or "")
            if section_id not in sections_by_id:
                continue
            terms = _match_terms(prefer.get("when_any") or [], haystack, hay_tokens)
            if not terms:
                continue
            if (
                section_id == "partitions"
                and _match_terms(["потолок", "короб"], haystack, hay_tokens)
                and all(normalize_text(term) in {"гкл", "гвл", "пгп"} for term in terms)
            ):
                continue
            deltas[section_id] = deltas.get(section_id, 0) + prefer_boost
            section_matches.setdefault(section_id, {}).setdefault(
                "conflict_prefer_terms", []
            ).extend(terms)
            applied.append(f"{rule_id}:prefer:{section_id}")

        for penalty in rule.get("penalize") or []:
            section_id = str(penalty.get("section_id") or "")
            if section_id not in sections_by_id:
                continue
            terms = _match_terms(penalty.get("when_any") or [], haystack, hay_tokens)
            if not terms:
                continue
            deltas[section_id] = deltas.get(section_id, 0) + penalty_value
            section_matches.setdefault(section_id, {}).setdefault(
                "conflict_penalty_terms", []
            ).extend(terms)
            applied.append(f"{rule_id}:penalize:{section_id}")

    for section_id, delta in deltas.items():
        if delta:
            section_scores[section_id] = section_scores.get(section_id, 0) + delta
    return applied


def _score_subtype(
    subtype: dict[str, Any],
    haystack: str,
    hay_tokens: list[str],
    weights: dict[str, int],
) -> tuple[int, dict[str, list[str]]]:
    matched: dict[str, list[str]] = {}
    strong = _match_terms(subtype.get("strong_terms") or [], haystack, hay_tokens)
    score = 0
    for term in strong:
        score += int(weights.get("subtype_strong_term", 5))
        normalized_term = normalize_text(term)
        if normalized_term == haystack:
            score += int(weights.get("exact_strong_phrase", 7)) * 2
        elif len(normalized_term.split()) > 1 and _boundary_pattern(normalized_term).search(haystack):
            # Explicit multi-word subtype phrases must outrank generic section
            # headers such as «отделочные работы» or «работы по полам».
            score += int(weights.get("exact_strong_phrase", 7))
    if strong:
        matched["subtype_strong_terms"] = strong

    pair_matches: list[str] = []
    for pair in subtype.get("action_object_pairs") or []:
        if not isinstance(pair, list) or len(pair) < 2:
            continue
        action, obj = str(pair[0]), str(pair[1])
        if _term_matches(action, haystack, hay_tokens) and _term_matches(
            obj, haystack, hay_tokens
        ):
            pair_matches.append(f"{action} + {obj}")
    if pair_matches:
        matched["action_object_pairs"] = pair_matches
        score += len(pair_matches) * int(weights.get("action_object_pair_boost", 3))

    if _match_terms(["формирование корыта", "разработка корыта"], haystack, hay_tokens):
        subtype_terms = " ".join(
            normalize_text(term)
            for term in subtype.get("strong_terms") or []
            if isinstance(term, str)
        )
        if "корыто" in subtype_terms:
            matched["subtype_context_terms"] = ["формирование корыта"]
            score += int(weights.get("action_object_pair_boost", 3))

    negative = _match_terms(subtype.get("negative_terms") or [], haystack, hay_tokens)
    if negative:
        matched["subtype_negative_terms"] = negative
        score += len(negative) * int(weights.get("negative_term", -6))
    return score, matched


def _best_subtype_hint(
    section: dict[str, Any],
    haystack: str,
    hay_tokens: list[str],
    weights: dict[str, int],
    allowed_subtype_ids: set[str] | frozenset[str] | None = None,
) -> tuple[int, dict[str, list[str]]]:
    best_score = 0
    best_matches: dict[str, list[str]] = {}
    for subtype in section.get("subtypes") or []:
        subtype_id = str(subtype.get("id") or "")
        if allowed_subtype_ids is not None and subtype_id not in allowed_subtype_ids:
            continue
        score, matched = _score_subtype(subtype, haystack, hay_tokens, weights)
        if score > best_score:
            best_score = score
            best_matches = matched
    return best_score, best_matches


def _confidence(score: int, delta: int, needs_review: bool, thresholds: dict[str, Any]) -> str:
    if needs_review:
        return "low"
    if score >= int(thresholds.get("auto_accept_min_score", 9)) and delta >= int(
        thresholds.get("min_delta_between_top_two", 3)
    ):
        return "high"
    return "medium"


def _related_sections(
    winner_section_id: str | None,
    matched_terms: dict[str, list[str]],
    haystack: str,
    hay_tokens: list[str],
    payload: dict[str, Any],
) -> list[str]:
    related: list[str] = []
    seen: set[str] = set()
    ambiguous = payload.get("ambiguous_terms") or {}
    matched_flat = [
        term
        for values in matched_terms.values()
        for term in values
        if isinstance(term, str)
    ]
    for ambiguous_term, section_ids in ambiguous.items():
        term_is_matched = any(
            normalize_text(ambiguous_term) == normalize_text(term)
            for term in matched_flat
        )
        if not term_is_matched:
            continue
        for section_id in section_ids or []:
            section_id = str(section_id)
            if section_id == winner_section_id or section_id in seen:
                continue
            seen.add(section_id)
            related.append(section_id)
    for rule in payload.get("related_section_rules") or []:
        if str(rule.get("main_section_id") or "") != str(winner_section_id or ""):
            continue
        if not _match_terms(rule.get("when_any") or [], haystack, hay_tokens):
            continue
        for section_id in rule.get("related_sections") or []:
            section_id = str(section_id)
            if section_id == winner_section_id or section_id in seen:
                continue
            seen.add(section_id)
            related.append(section_id)
    return related


def _section_candidates(
    ranked: list[tuple[str, int, dict[str, list[str]]]],
    sections_by_id: dict[str, dict[str, Any]],
    thresholds: dict[str, Any],
) -> list[ClassificationCandidate]:
    candidates: list[ClassificationCandidate] = []
    for index, (section_id, score, matched) in enumerate(ranked[:5], start=1):
        next_score = ranked[index][1] if index < len(ranked) else 0
        delta = score - next_score
        needs_review = score < int(thresholds.get("auto_accept_min_score", 9)) or delta < int(
            thresholds.get("min_delta_between_top_two", 3)
        )
        section = sections_by_id[section_id]
        candidates.append(
            ClassificationCandidate(
                rank=index,
                stage="section",
                section_code=section_id,
                section_name=section.get("title"),
                score=score,
                section_score=score,
                delta_to_next=delta,
                confidence=_confidence(score, delta, needs_review, thresholds),
                needs_review=needs_review,
                matched_terms=matched,
                reason="section_score",
            )
        )
    return candidates


def _subtype_candidates(
    section: dict[str, Any],
    section_score: int,
    haystack: str,
    hay_tokens: list[str],
    weights: dict[str, int],
    thresholds: dict[str, Any],
    payload: dict[str, Any],
    allowed_subtype_ids: set[str] | frozenset[str] | None = None,
) -> tuple[list[ClassificationCandidate], dict[str, list[str]]]:
    scored: list[tuple[dict[str, Any], int, dict[str, list[str]]]] = []
    for subtype in section.get("subtypes") or []:
        subtype_id = str(subtype.get("id") or "")
        if allowed_subtype_ids is not None and subtype_id not in allowed_subtype_ids:
            continue
        score, matched = _score_subtype(subtype, haystack, hay_tokens, weights)
        scored.append((subtype, score, matched))
    scored.sort(key=lambda item: (item[1], len(str(item[0].get("title") or ""))), reverse=True)

    candidates: list[ClassificationCandidate] = []
    for index, (subtype, score, matched) in enumerate(scored[:5], start=1):
        next_score = scored[index][1] if index < len(scored) else 0
        delta = score - next_score
        needs_review = score <= 0 or delta < int(thresholds.get("min_delta_between_top_two", 3))
        subtype_code = f"{section['id']}/{subtype['id']}"
        related = _related_sections(
            str(section["id"]), matched, haystack, hay_tokens, payload
        )
        candidates.append(
            ClassificationCandidate(
                rank=index,
                stage="subtype",
                section_code=str(section["id"]),
                section_name=section.get("title"),
                subtype_code=subtype_code,
                subtype_name=subtype.get("title"),
                score=section_score + score,
                section_score=section_score,
                subtype_score=score,
                delta_to_next=delta,
                confidence=_confidence(score, delta, needs_review, thresholds),
                needs_review=needs_review,
                matched_terms=matched,
                related_sections=related,
                reason="subtype_score",
            )
        )
    best_matches = scored[0][2] if scored else {}
    return candidates, best_matches


_DEMOLITION_ACTION_TERMS = (
    "демонтаж",
    "демотаж",
    "демонтажные",
    "демонтировать",
    "демонтируем",
    "демонтируется",
    "разборка",
    "разобрать",
    "снятие",
    "снять",
    "удаление",
    "удалить",
)
_DEMOLITION_OBJECT_TERMS = (
    "потолок", "армстронг", "грильято", "реечный потолок", "натяжной потолок",
    "каркас потолка", "обрешетка потолка", "потолочный плинтус",
    "стена", "перегородка", "короб гкл", "стеновая панель", "обои",
    "пол", "стяжка", "линолеум", "ламинат", "паркет", "фанера", "оргалит",
    "плинтус", "порожек", "напольное покрытие", "плитка пола", "подсыпка",
    "сантехника", "унитаз", "инсталляция", "биде", "писсуар", "ванна",
    "душевая кабина", "поддон", "раковина", "мойка", "смеситель",
    "полотенцесушитель", "радиатор", "конвектор", "труба", "водоснабжение",
    "канализация", "отопление",
    "кабель", "проводка", "розетка", "выключатель", "светильник", "щит",
    "автомат", "лоток", "электрическая коробка",
    "вентиляция", "воздуховод", "гибкий воздуховод", "вентиляционный короб",
    "вентилятор", "вентиляционная решетка", "кондиционер", "сплит система",
    "окно", "дверь", "проем", "конструкция",
)
_DEMOLITION_SUBTYPE_IDS = frozenset(
    {
        "general_structural_demolition",
        "ceiling_demolition",
        "wall_demolition",
        "floor_demolition",
        "plumbing_demolition",
        "electrical_demolition",
        "hvac_demolition",
        "openings_diamond_cutting",
    }
)


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(normalize_text(term) in text for term in terms)


def _has_demolition_action(text: str) -> bool:
    tokens = text.split()
    return any(
        (normalize_text(term) in tokens)
        if len(normalize_text(term).split()) == 1
        else bool(_boundary_pattern(normalize_text(term)).search(text))
        for term in _DEMOLITION_ACTION_TERMS
    )


def resolve_demolition_object(
    item_text: str,
    section_context: str | None = None,
) -> str | None:
    """Resolve the physical object of demolition.

    The item itself always wins. Section context is only a fallback for generic
    rows such as «Демонтаж оборудования».
    """
    item = normalize_text(item_text)
    section = normalize_text(section_context)
    if not _has_demolition_action(item):
        return None

    groups: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("hvac", (
            "воздуховод", "гибк воздуховод", "вентиляцион короб", "вентилятор",
            "вентиляцион решет", "кондиционер", "сплит систем", "вентиляц",
        )),
        ("plumbing", (
            "унитаз", "инсталляц", "биде", "писсуар", "ванн", "душев",
            "поддон", "раковин", "мойк", "смесител", "полотенцесушител",
            "радиатор", "конвектор", "водоснабжен", "канализац", "сантех",
            "труб отоплен", "труб вод", "труб канал",
        )),
        ("electrical", (
            "кабел", "проводк", "розет", "выключател", "светильник", "щит",
            "автомат", "электрооборуд", "электрическ лот", "кабельн лот",
            "электрическ короб",
        )),
        ("floor", (
            "стяж", "линоле", "ламинат", "паркет", "фанер", "оргалит",
            "плинтус", "порож", "дощат пол", "напольн покрыт", "пол плит",
            "плитк пола", "подсыпк", "полы", "пола",
        )),
        ("ceiling", (
            "потол", "армстронг", "грильято", "реечн", "натяжн",
            "каркас потол", "обрешетк потол", "обрешётк потол",
        )),
        ("wall_partition", (
            "перегород", "короб из гкл", "коробов из гкл", "короб гкл", "стенов панел",
            "настенн плит", "штукатурк стен", "обои", "краск со стен",
            "стены", "стена",
        )),
        ("opening", ("оконн блок", "дверн блок", "окно", "двер", "проем", "проём")),
    )
    for object_id, terms in groups:
        if _contains_any(item, terms):
            return object_id

    # Section context is deliberately weaker than the item text.
    for object_id, terms in groups:
        if _contains_any(section, terms):
            return object_id
    return "general"


def _has_demolition_intent(haystack: str, hay_tokens: list[str]) -> bool:
    return bool(
        _has_demolition_action(haystack)
        and _match_terms(list(_DEMOLITION_OBJECT_TERMS), haystack, hay_tokens)
    )


def _explicit_object_priority_pair(
    haystack: str,
    section_context: str | None = None,
) -> tuple[str, str, str, list[str]] | None:
    """Resolve unambiguous action/object phrases before ordinary scoring."""
    # Logistics and protection must be resolved before generic objects such as
    # doors, floors or quoted source-work descriptions can steal the row.
    if _contains_any(haystack, (
        "разгрузк материал", "доставк материал", "погрузк материал",
        "вынос мусор", "вывоз мусор", "контейнер для мусор",
        "контейнер для вывоз", "строительн мусор",
    )):
        return (
            "mobilization", "logistics_cleanup", "logistics_cleanup_object_priority",
            ["логистика", "мусор"],
        )
    if _contains_any(haystack, (
        "укрытие пленк", "укрытие плёнк", "защита существующ отделк",
        "укрытие мебел", "защита мебел", "укрытие полов", "укрытие стен",
    )):
        return (
            "mobilization", "site_setup", "site_protection_object_priority",
            ["защита существующей отделки"],
        )

    demolition_object = resolve_demolition_object(haystack, section_context)
    if demolition_object:
        subtype_by_object = {
            "ceiling": "ceiling_demolition",
            "wall_partition": "wall_demolition",
            "floor": "floor_demolition",
            "plumbing": "plumbing_demolition",
            "electrical": "electrical_demolition",
            "hvac": "hvac_demolition",
            "opening": "openings_diamond_cutting",
            "general": "general_structural_demolition",
        }
        subtype_id = subtype_by_object[demolition_object]
        return (
            "reconstruction_works",
            subtype_id,
            f"demolition_object_priority_{demolition_object}",
            ["demolition", demolition_object],
        )

    demolition = _has_demolition_action(haystack)

    if not demolition and _contains_any(haystack, (
        "очистка стар", "очистка ветх", "расчистка стар", "снятие стар",
    )) and _contains_any(haystack, ("краск", "кле", "побел", "обо", "покрыт")):
        if "потол" in haystack:
            return (
                "reconstruction_works", "ceiling_demolition",
                "old_ceiling_coating_removal_priority", ["удаление старого покрытия потолка"],
            )
        if _contains_any(haystack, ("стен", "обо")):
            return (
                "reconstruction_works", "wall_demolition",
                "old_wall_coating_removal_priority", ["удаление старого покрытия стен"],
            )
        if _contains_any(haystack, ("пол", "линоле", "паркет", "фанер")):
            return (
                "reconstruction_works", "floor_demolition",
                "old_floor_coating_removal_priority", ["удаление старого покрытия пола"],
            )

    if not demolition and _contains_any(haystack, (
        "кабель интернет", "кабеля интернет", "кабель tv", "кабеля tv", "интернет и tv", "витая пара",
        "кабель utp", "кабель ftp", "скс", "структурированн кабельн",
    )):
        return (
            "mep_internal", "structured_cabling",
            "structured_cabling_object_priority", ["СКС/интернет/TV"],
        )

    if not demolition and _contains_any(haystack, (
        "грунтование потол", "грунтовка потол", "шпаклевка потол", "шпатлевка потол",
        "грунтование стен", "грунтовка стен", "шпаклевка стен", "шпатлевка стен",
    )):
        return (
            "interior_finishing", "putty_primer",
            "putty_primer_surface_object_priority", ["грунтовка/шпаклевка поверхности"],
        )

    if not demolition and _contains_any(haystack, (
        "ремонт потол", "устранение мелких дефектов потол", "расчистка руст",
        "заделка руст", "ремонтными смесями потол",
    )):
        return (
            "interior_finishing", "plastering",
            "ceiling_repair_object_priority", ["ремонт потолка"],
        )

    if not demolition and _contains_any(haystack, (
        "прозвонка кабел", "прокладка лотк", "монтаж контактор",
        "установка электрощит", "установка распределительн панел",
        "установка автомат", "монтаж регулятора теплого пола",
    )):
        return (
            "mep_internal", "electrical",
            "electrical_equipment_object_priority", ["электромонтажное оборудование"],
        )

    if "гидролок" in haystack:
        if _contains_any(haystack, ("подключ", "расключ")):
            return (
                "mep_internal", "electrical", "hydrolock_electrical_connection_priority",
                ["подключение гидролока"],
            )
        if _contains_any(haystack, ("монтаж", "установ")):
            return (
                "mep_internal", "water_supply", "hydrolock_water_installation_priority",
                ["монтаж гидролока"],
            )

    if not demolition and _contains_any(haystack, (
        "штроблен", "устройство штроб", "штроба в", "бурение сквозн отверст",
        "отверстие для электроточ", "устройство ниш", "ниша в бетон",
        "ниша в кирпич", "ниша в газоблок",
    )) and not _contains_any(haystack, ("без штроб", "готовой штроб", "готовую штроб")):
        return (
            "reconstruction_works", "chasing_drilling_niches",
            "chasing_drilling_niches_object_priority",
            ["штробление/бурение/ниша"],
        )

    if not demolition and _contains_any(haystack, (
        "монтаж откосов пвх", "оконн откос", "дверн откос", "подоконник",
        "оконн отлив", "отлив окон", "отделка откос",
    )):
        return (
            "windows_doors", "window_slopes_sills", "window_slopes_sills_object_priority",
            ["оконные откосы/подоконник"],
        )

    if not demolition and _contains_any(haystack, (
        "люк невидим", "люк невидимк", "люк неведим", "люк неведимк", "ревизионн люк", "техническ люк",
    )):
        return (
            "windows_doors", "technical_doors_hatches",
            "technical_hatch_object_priority", ["технический люк"],
        )

    if not demolition and _contains_any(haystack, (
        "монтаж вгкл", "монтаж гкл по каркас", "обшивка вгкл",
        "обшивка гкл по каркас", "каркас перегород", "перегородка из гкл",
    )) and "потол" not in haystack:
        return (
            "partitions", "drywall_partitions",
            "drywall_partition_object_priority", ["ГКЛ/ВГКЛ по каркасу"],
        )

    # Special masonry must be resolved before generic brick masonry scoring.
    special_masonry = resolve_special_masonry_operation(haystack, section_context or "")
    if not demolition and special_masonry == "facade_cladding":
        return (
            "interior_finishing", "facade_finishing",
            "facade_facing_masonry_object_priority", ["облицовочная кладка фасада"],
        )
    if not demolition and special_masonry == "arm_belt_masonry":
        return (
            "load_bearing_walls", "arm_belts_lintels",
            "brick_arm_belt_object_priority", ["кирпичный армопояс"],
        )
    if not demolition and special_masonry == "vent_shaft_masonry":
        return (
            "load_bearing_walls", "vent_shafts_masonry",
            "vent_shaft_masonry_object_priority", ["кирпичная кладка вентканалов"],
        )
    if not demolition and special_masonry == "brick_pillar_masonry":
        combined = f"{haystack} {section_context or ''}"
        if _contains_any(combined, (
            "забор", "огражден", "ограждён", "штакет", "ворот", "калитк", "благоустрой",
        )):
            return (
                "landscape", "small_forms",
                "brick_fence_pillar_object_priority", ["кирпичные столбы ограждения"],
            )
        if _contains_any(combined, (
            "здани", "каркас", "несущ", "колонна здания", "колонны здания",
        )):
            return (
                "structural_frame", "columns_beams_girders",
                "brick_building_column_object_priority", ["кирпичные колонны здания"],
            )

    # In this domain the canonical «Утепление стен» means exterior insulation.
    # Explicit interior insulation is blocked before scoring in classify_work_cascade.
    if not demolition and _contains_any(haystack, (
        "теплоизоляц стен", "утепление стен", "утепление наружн стен",
        "утепление фасад", "теплоизоляц фасад",
    )):
        return (
            "insulation", "facade_wall_insulation",
            "facade_wall_insulation_object_priority", ["утепление стен"],
        )

    if not demolition and _contains_any(haystack, (
        "окраска стен", "покраска стен", "окраска потол", "покраска потол",
        "нанесение краски", "окрашивание стен",
    )):
        return (
            "interior_finishing", "painting",
            "painting_object_priority", ["окраска поверхности"],
        )

    if not demolition and _contains_any(haystack, (
        "жалюзи", "рулонн штор", "римск штор", "светофильтр",
        "внутренн карниз", "солнцезащитн систем",
    )):
        return (
            "windows_doors", "window_coverings_blinds_curtains",
            "window_coverings_object_priority", ["жалюзи/шторы"],
        )

    if not demolition and _contains_any(haystack, ("шумоизоляц", "звукоизоляц", "зипс")):
        return (
            "insulation", "sound_acoustic_insulation", "sound_insulation_object_priority",
            ["звукоизоляция"],
        )

    if not demolition and "потол" in haystack and "светильник" not in haystack:
        if "натяжн" in haystack:
            return (
                "interior_finishing", "stretch_ceilings", "stretch_ceiling_object_priority",
                ["натяжной потолок"],
            )
        if _contains_any(haystack, ("армстронг", "грильято", "реечн", "подвесн")):
            return (
                "interior_finishing", "suspended_ceilings", "suspended_ceiling_object_priority",
                ["подвесной потолок"],
            )
        if "гкл" in haystack or "гипсокарт" in haystack:
            return (
                "interior_finishing", "gkl_ceilings", "gkl_ceiling_object_priority",
                ["потолок из ГКЛ"],
            )
        if _contains_any(haystack, ("потолочн плинт", "молдинг", "лепнин")):
            return (
                "interior_finishing", "ceiling_moulding", "ceiling_moulding_object_priority",
                ["потолочный плинтус/молдинг"],
            )

    if not demolition and _contains_any(haystack, (
        "спортивн покрыт", "спортивн пол", "ласточкин хвост",
        "замковое спортивн покрыт", "модульн спортивн покрыт",
        "резинов плит с замк",
    )):
        return (
            "interior_finishing", "sports_floor_finishes", "sports_floor_object_priority",
            ["спортивное покрытие"],
        )
    if not demolition and _contains_any(haystack, (
        "плинтус", "порож", "профиль примыкан",
    )) and "потолочн" not in haystack:
        return (
            "interior_finishing", "baseboards_trims", "baseboard_object_priority",
            ["плинтус/порожек"],
        )
    if not demolition and _contains_any(haystack, (
        "линоле", "ламинат", "паркет", "ковролин", "фанера под",
        "инженерн дос", "инжинерн дос", "массивн дос", "настил фанер", "настил osb", "настил осп",
    )):
        return (
            "interior_finishing", "floor_coverings", "floor_covering_object_priority",
            ["напольное покрытие"],
        )
    if not demolition and "пол" in haystack and _contains_any(haystack, (
        "подготов", "грунтов", "обеспылив", "очист",
    )):
        return (
            "floor_screed", "floor_base_preparation", "floor_base_preparation_priority",
            ["подготовка основания пола"],
        )

    if "наливн" in haystack and "пол" in haystack:
        preparation = any(
            term in haystack
            for term in ("подметан", "обеспылив", "грунтов", "подготов", "очист")
        )
        if preparation:
            return (
                "floor_screed", "floor_base_preparation",
                "floor_object_preparation_priority",
                ["пол", "наливной пол", "подготовка основания"],
            )
        return (
            "floor_screed", "self_leveling_floor",
            "self_leveling_floor_object_priority", ["наливной пол"],
        )

    if re.search(r"\bкран\w*\s+шаров\w*\b", haystack):
        return (
            "mep_internal", "water_supply", "water_valve_object_priority",
            ["шаровой кран"],
        )

    if (
        "двер" in haystack
        and re.search(r"\b(?:установ\w*|монтаж\w*)\b", haystack)
        and not demolition
    ):
        if "противопожар" in haystack:
            subtype_id = "fire_doors"
        elif any(term in haystack for term in ("входн", "наружн", "стальн", "металлическ")):
            subtype_id = "exterior_doors"
        elif any(term in haystack for term in ("деревян", "филенчат", "межкомнат", "распашн", "раздвижн")):
            subtype_id = "interior_doors"
        else:
            return None
        return (
            "windows_doors", subtype_id, "door_installation_object_priority",
            ["установка двери"],
        )

    if "гкл" in haystack and "шв" in haystack and any(
        term in haystack for term in ("задел", "шпаклев", "грунтов", "шлифов")
    ):
        return (
            "interior_finishing", "gkl_surface_finishing",
            "gkl_seam_finishing_object_priority", ["швы гкл"],
        )

    return None


def _explicit_object_priority_result(
    *,
    pair: tuple[str, str, str, list[str]],
    sections_by_id: dict[str, dict[str, Any]],
    resolved_role: str,
    version: str,
    scope_name: str,
    scope_fields: dict[str, Any],
    thresholds: dict[str, Any],
) -> ClassificationResult | None:
    section_id, subtype_id, reason, terms = pair
    section = sections_by_id.get(section_id)
    if not section:
        return None
    subtype = next(
        (
            item
            for item in section.get("subtypes") or []
            if isinstance(item, dict) and str(item.get("id") or item.get("code") or "") == subtype_id
        ),
        None,
    )
    if not subtype:
        return None
    score = int(thresholds.get("auto_accept_min_score", 9)) + 8
    code = f"{section_id}/{subtype_id}"
    candidate = ClassificationCandidate(
        rank=1,
        stage="subtype",
        section_code=section_id,
        section_name=section.get("title"),
        subtype_code=code,
        subtype_name=subtype.get("title"),
        score=score,
        section_score=score,
        subtype_score=score,
        delta_to_next=score,
        confidence="high",
        needs_review=False,
        source="object_priority",
        matched_terms={"object_priority": terms},
        reason=reason,
    )
    return ClassificationResult(
        section_code=section_id,
        section_name=section.get("title"),
        subtype_code=code,
        subtype_name=subtype.get("title") or UNKNOWN_SUBTYPE_NAME,
        score=score,
        confidence="high",
        needs_review=False,
        source="object_priority",
        matched_terms={"object_priority": terms},
        candidates=[candidate],
        related_sections=[],
        reason=reason,
        dictionary_version=version,
        row_role=resolved_role,
        object_priority_rule=reason,
        **scope_fields,
    )



def _operation_resolution_policy(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or _load_dictionary()
    policy = payload.get("operation_object_resolution_policy")
    return policy if isinstance(policy, dict) else {}


def _tz_operation_package_additions() -> dict[str, dict[str, Any]]:
    return {
        "excavation_with_loading_package": {
            "code": "excavation_with_loading_package",
            "kind": "package",
            "included_operations": ["excavation", "soil_loading"],
            "component_units": {"excavation": "m3", "soil_loading": "m3"},
        },
        "monolithic_floor_slab_package": {
            "code": "monolithic_floor_slab_package",
            "kind": "package",
            "included_operations": [
                "formwork_installation",
                "rebar_installation",
                "concrete_placement",
                "concrete_curing",
                "formwork_stripping",
            ],
            "component_units": {
                "formwork_installation": "m2",
                "rebar_installation": "t",
                "concrete_placement": "m3",
                "concrete_curing": "m2",
                "formwork_stripping": "m2",
            },
        },
        "monolithic_lintel_package": {
            "code": "monolithic_lintel_package",
            "kind": "package",
            "included_operations": [
                "formwork_installation",
                "rebar_installation",
                "concrete_placement",
                "formwork_stripping",
            ],
            "component_units": {
                "formwork_installation": "m2",
                "rebar_installation": "t",
                "concrete_placement": "m3",
                "formwork_stripping": "m2",
            },
        },
        "mauerlat_installation_package": {
            "code": "mauerlat_installation_package",
            "kind": "package",
            "included_operations": ["mauerlat_installation", "antiseptic_treatment"],
            "component_units": {"mauerlat_installation": "m", "antiseptic_treatment": "m3"},
        },
        "basement_wall_protection_package": {
            "code": "basement_wall_protection_package",
            "kind": "package",
            "included_operations": [
                "foundation_wall_waterproofing",
                "foundation_wall_thermal_insulation",
            ],
            "component_units": {
                "foundation_wall_waterproofing": "m2",
                "foundation_wall_thermal_insulation": "m2",
            },
        },
    }


@lru_cache(maxsize=16)
def _variant_operation_alias_catalog(project_variant_id: str) -> dict[str, Any]:
    payload = _load_dictionary()
    variant: dict[str, Any] | None = None
    for estimate_type in _hierarchy_estimate_types(payload):
        for candidate in estimate_type.get("project_variants") or []:
            if not isinstance(candidate, dict):
                continue
            if (
                str(candidate.get("id") or "") == str(project_variant_id)
                or str(candidate.get("number") or "") == str(project_variant_id)
            ):
                variant = candidate
                break
        if variant is not None:
            break
    if variant is None:
        return {}

    registry = variant.get("operation_registry") or {}
    operations = registry.get("operations") or {}
    packages = dict(registry.get("operation_packages") or {})
    packages.update(_tz_operation_package_additions())
    alias_catalog = variant.get("classification_catalog") or {}
    stages = variant.get("stages") or []

    operation_to_stages: dict[str, set[str]] = {}
    package_to_stages: dict[str, set[str]] = {}
    stage_options: dict[str, list[dict[str, Any]]] = {}
    stage_packages: dict[str, set[str]] = {}
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_number = str(stage.get("number") or "")
        if not stage_number:
            continue
        stage_options[stage_number] = [
            option for option in (stage.get("stage_options") or []) if isinstance(option, dict)
        ]
        stage_packages[stage_number] = {
            str(code) for code in (stage.get("operation_packages") or []) if code
        }
        primary_code = str(stage.get("primary_operation_code") or "")
        if primary_code:
            operation_to_stages.setdefault(primary_code, set()).add(stage_number)
        for operation in stage.get("operations") or []:
            if not isinstance(operation, dict):
                continue
            code = str(operation.get("operation_code") or "")
            if code:
                operation_to_stages.setdefault(code, set()).add(stage_number)
        for code in stage_packages[stage_number]:
            package_to_stages.setdefault(code, set()).add(stage_number)
        for option in stage_options[stage_number]:
            for code in option.get("operation_codes") or []:
                if code:
                    operation_to_stages.setdefault(str(code), set()).add(stage_number)
            for code in option.get("package_codes") or []:
                if code:
                    package_to_stages.setdefault(str(code), set()).add(stage_number)

    return {
        "payload": {"project_variant": variant},
        "operations": operations if isinstance(operations, dict) else {},
        "packages": packages if isinstance(packages, dict) else {},
        "alias_groups": [
            group for group in (alias_catalog.get("alias_groups") or []) if isinstance(group, dict)
        ],
        "alias_policy": alias_catalog.get("alias_policy") or {},
        "operation_to_stages": operation_to_stages,
        "package_to_stages": package_to_stages,
        "stage_options": stage_options,
        "stage_packages": stage_packages,
    }


def _context_term_present(term: str, haystack: str, tokens: list[str]) -> bool:
    """Match context gates by phrase or stable word stem.

    Source aliases intentionally contain stems such as ``вент``, ``уров`` and
    ``перемыч``. The regular alias matcher is phrase-oriented and therefore
    cannot be used as the only gate for these values.
    """
    normalized = normalize_text(term)
    if not normalized:
        return False
    if _match_terms([term], haystack, tokens):
        return True
    term_tokens = [token for token in normalized.split() if token]
    if not term_tokens:
        return False
    for term_token in term_tokens:
        if len(term_token) < 4:
            if term_token not in tokens:
                return False
            continue
        prefix_len = min(6, len(term_token))
        prefix = term_token[:prefix_len]
        if not any(
            token.startswith(prefix) or term_token.startswith(token[:prefix_len])
            for token in tokens
            if len(token) >= 4
        ):
            return False
    return True


def _operation_context_gate(
    definition: dict[str, Any],
    *,
    item_haystack: str,
    context_haystack: str,
) -> tuple[bool, bool]:
    combined = " ".join(part for part in (item_haystack, context_haystack) if part)
    combined_tokens = combined.split()
    required_any = [str(term) for term in (definition.get("required_terms_any") or []) if term]
    required_all = [str(term) for term in (definition.get("required_terms_all") or []) if term]
    excluded = [str(term) for term in (definition.get("excluded_terms") or definition.get("negative_terms") or []) if term]
    if excluded and any(_context_term_present(term, combined, combined_tokens) for term in excluded):
        return False, False
    required_matched = False
    if required_any:
        required_matched = any(
            _context_term_present(term, combined, combined_tokens)
            for term in required_any
        )
        if not required_matched:
            return False, False
    if required_all:
        for term in required_all:
            if not _context_term_present(term, combined, combined_tokens):
                return False, required_matched
        required_matched = True
    # Context may be supplied either by the section/stage or explicitly in
    # the row text itself (for example ``обрешетка фасада``).
    if bool(definition.get("requires_context")) and not context_haystack and not required_matched:
        return False, required_matched
    return True, required_matched


_RUSSIAN_INFLECTION_SUFFIXES = tuple(
    sorted(
        {
            "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими",
            "ной", "ный", "ная", "ное", "ные", "ную", "нее",
            "ого", "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой",
            "ам", "ям", "ах", "ях", "ом", "ем", "ов", "ев", "ей",
            "а", "я", "ы", "и", "у", "ю", "е", "о", "ь",
        },
        key=len,
        reverse=True,
    )
)


def _operation_token_stem(token: str) -> str:
    normalized = normalize_text(token)
    if not normalized or normalized.isascii():
        return normalized
    for suffix in _RUSSIAN_INFLECTION_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized


def _operation_term_match(term: str, haystack: str, tokens: list[str]) -> tuple[bool, bool]:
    normalized = normalize_text(term)
    if not normalized:
        return False, False
    exact = normalized == haystack
    matched = bool(exact or _match_terms([term], haystack, tokens))
    if not matched:
        stop_tokens = {"из", "на", "по", "для", "под", "при", "в", "и", "с", "со", "к"}
        term_tokens = [
            token for token in normalized.split()
            if token not in stop_tokens
            and (len(token) >= 4 or (token.isascii() and len(token) >= 2))
        ]
        if term_tokens:
            matched = all(
                any(
                    (
                        (
                            _operation_token_stem(term_token)
                            == _operation_token_stem(hay_token)
                        )
                        or (
                            min(
                                len(_operation_token_stem(term_token)),
                                len(_operation_token_stem(hay_token)),
                            ) >= 6
                            and abs(
                                len(_operation_token_stem(term_token))
                                - len(_operation_token_stem(hay_token))
                            ) <= 3
                            and (
                                _operation_token_stem(term_token).startswith(
                                    _operation_token_stem(hay_token)
                                )
                                or _operation_token_stem(hay_token).startswith(
                                    _operation_token_stem(term_token)
                                )
                            )
                        )
                    )
                    for hay_token in tokens
                    if len(hay_token) >= 4
                )
                for term_token in term_tokens
            )
    return matched, exact


def _option_context_score(option: dict[str, Any], item_haystack: str) -> float:
    score = 0.0
    title = str(option.get("title") or "")
    title_terms = [title] + [
        token for token in normalize_text(title).split() if len(token) >= 4
    ]
    if title and _match_terms(title_terms, item_haystack, item_haystack.split()):
        score += 0.12
    applicability = option.get("applicability") or {}
    method = str(applicability.get("installation_method") or "")
    if method == "crane" and _contains_any(item_haystack, ("кран", "автокран", "механизирован")):
        score += 0.2
    if method == "manual" and _contains_any(item_haystack, ("ручн", "вручную")):
        score += 0.2
    return score


def _preferred_option_for_operation(
    catalog: dict[str, Any],
    *,
    stage_number: str | None,
    operation_code: str | None,
    package_code: str | None,
    item_haystack: str,
) -> str | None:
    if not stage_number:
        return None
    matches: list[tuple[float, str]] = []
    for option in catalog.get("stage_options", {}).get(stage_number, []):
        option_id = str(option.get("id") or option.get("number") or "")
        if not option_id:
            continue
        supports = False
        if operation_code and operation_code in {str(code) for code in (option.get("operation_codes") or [])}:
            supports = True
        if package_code and package_code in {str(code) for code in (option.get("package_codes") or [])}:
            supports = True
        if supports:
            matches.append((_option_context_score(option, item_haystack), option_id))
    if not matches:
        return None
    matches.sort(reverse=True)
    if len(matches) == 1:
        return matches[0][1]
    if matches[0][0] > matches[1][0]:
        return matches[0][1]
    return None


def _find_covering_package(
    catalog: dict[str, Any],
    operation_codes: set[str],
    preferred_stage_numbers: set[str],
) -> str | None:
    if len(operation_codes) < 2:
        return None
    candidates: list[str] = []
    for code, package in catalog.get("packages", {}).items():
        if not isinstance(package, dict):
            continue
        included = {str(item) for item in (package.get("included_operations") or [])}
        if not operation_codes.issubset(included):
            continue
        package_stages = catalog.get("package_to_stages", {}).get(str(code), set())
        if preferred_stage_numbers and package_stages and not (preferred_stage_numbers & package_stages):
            continue
        candidates.append(str(code))
    return candidates[0] if len(candidates) == 1 else None


def _rule_operation_result(
    *,
    code: str | None,
    kind: str,
    score: float,
    matched_term: str,
    reason: str,
    needs_review: bool = False,
    target_codes: tuple[str, ...] = (),
    preferred_stage_number: str | None = None,
) -> OperationDetectionResult:
    candidate = OperationDetectionCandidate(
        code=code,
        kind=kind,
        score=score,
        matched_terms=(matched_term,),
        source="tz_rate_resolution_rule",
        stage_numbers=(preferred_stage_number,) if preferred_stage_number else (),
        target_codes=target_codes,
        exact=True,
        context_gate_matched=True,
    )
    return OperationDetectionResult(
        operation_code=code if kind != "multi_operation" else None,
        operation_package_code=code if kind == "package" else None,
        confidence_score=score,
        matched_terms=(matched_term,),
        candidates=(candidate,),
        needs_review=needs_review,
        reason=reason,
        preferred_stage_number=preferred_stage_number,
        multi_operation_codes=target_codes,
    )


def _tz_operation_detection_override(item_text: str, haystack: str) -> OperationDetectionResult | None:
    """Address known operation-resolution failures from TZ_rate_resolution_fixes.md."""
    if not haystack:
        return None

    has_conjunction = bool(re.search(r"(?:,|;|\+|\s/\s|\bи\b)", haystack))
    if (
        has_conjunction
        and "мауэрлат" in haystack
        and re.search(r"\bмонтаж\w*", haystack)
        and re.search(r"\bантисепт\w*", haystack)
    ):
        return _rule_operation_result(
            code="mauerlat_installation_package",
            kind="package",
            score=0.995,
            matched_term=item_text,
            reason="operation_package_match",
            target_codes=("mauerlat_installation", "antiseptic_treatment"),
        )
    if (
        has_conjunction
        and re.search(r"\bгидроизоляц\w*", haystack)
        and re.search(r"\bутепл\w*", haystack)
        and re.search(r"\b(цокол|цоколь|фундамент|наружн\w*\s+стен)\w*", haystack)
    ):
        return _rule_operation_result(
            code="basement_wall_protection_package",
            kind="package",
            score=0.995,
            matched_term=item_text,
            reason="operation_package_match",
            target_codes=("foundation_wall_waterproofing", "foundation_wall_thermal_insulation"),
        )
    if (
        re.search(r"\b(котлован|транше)\w*", haystack)
        and re.search(r"\b(погрузк|вывоз)\w*", haystack)
        and re.search(r"\b(грунт|разработк|выемк)\w*", haystack)
    ):
        return _rule_operation_result(
            code="excavation_with_loading_package",
            kind="package",
            score=0.995,
            matched_term=item_text,
            reason="operation_package_match",
            target_codes=("excavation", "soil_loading"),
        )
    if re.search(r"\b(монтаж|устройств|установк)\w*\s+опалубк\w*", haystack):
        return _rule_operation_result(
            code="formwork_installation",
            kind="atomic",
            score=0.99,
            matched_term=item_text,
            reason="variant_operation_alias_match",
        )
    if re.search(r"\bустройств\w*\s+монолитн\w*\s+(?:железобетонн\w*\s+)?перекрыт\w*", haystack):
        return _rule_operation_result(
            code="monolithic_floor_slab_package",
            kind="package",
            score=0.985,
            matched_term=item_text,
            reason="operation_package_match",
            target_codes=(
                "formwork_installation",
                "rebar_installation",
                "concrete_placement",
                "concrete_curing",
                "formwork_stripping",
            ),
        )
    if re.search(r"\bустройств\w*\s+монолитн\w*\s+(?:железобетонн\w*\s+|жб\s+)?перемыч", haystack):
        return _rule_operation_result(
            code="monolithic_lintel_package",
            kind="package",
            score=0.985,
            matched_term=item_text,
            reason="operation_package_match",
            target_codes=(
                "formwork_installation",
                "rebar_installation",
                "concrete_placement",
                "formwork_stripping",
            ),
        )
    if re.search(r"\bпесчан\w*\s+подготовк\w*", haystack):
        return _rule_operation_result(
            code="sand_base_installation",
            kind="atomic",
            score=0.99,
            matched_term=item_text,
            reason="variant_operation_alias_match",
        )
    if re.search(r"\bармирован\w*", haystack):
        return _rule_operation_result(
            code="rebar_installation",
            kind="atomic",
            score=0.99,
            matched_term=item_text,
            reason="variant_operation_alias_match",
        )
    if re.search(r"\bбетонирован\w*", haystack):
        return _rule_operation_result(
            code="concrete_placement",
            kind="atomic",
            score=0.99,
            matched_term=item_text,
            reason="variant_operation_alias_match",
        )
    if re.search(r"\bраспалубк\w*", haystack):
        return _rule_operation_result(
            code="formwork_stripping",
            kind="atomic",
            score=0.99,
            matched_term=item_text,
            reason="variant_operation_alias_match",
        )
    if re.search(r"\bантисепт\w*", haystack):
        return _rule_operation_result(
            code="antiseptic_treatment",
            kind="atomic",
            score=0.99,
            matched_term=item_text,
            reason="variant_operation_alias_match",
        )
    if (
        re.search(r"\b(утепленн\w*\s+шведск\w*\s+плит|ушп|тепл\w*\s+пол|ребр\w*\s+жесткост|инженерн\w*\s+выпуск)\w*", haystack)
    ):
        return _rule_operation_result(
            code="foundation_usp_complete",
            kind="package",
            score=0.99,
            matched_term=item_text,
            reason="operation_package_match",
        )
    return None


def _legacy_operation_detection(item_text: str, payload: dict[str, Any]) -> OperationDetectionResult:
    policy = _operation_resolution_policy(payload)
    haystack = normalize_text(item_text or "")
    hay_tokens = haystack.split()
    if not haystack:
        return OperationDetectionResult(None, None, None, ())
    matches: list[tuple[int, str, list[str]]] = []
    for operation_code, terms in (policy.get("operations") or {}).items():
        if not isinstance(terms, list):
            continue
        matched = _match_terms([str(term) for term in terms], haystack, hay_tokens)
        if matched:
            specificity = max(len(normalize_text(term)) for term in matched)
            matches.append((specificity, str(operation_code), matched))
    if not matches:
        return OperationDetectionResult(None, None, None, ())
    matches.sort(key=lambda item: (item[0], len(item[2])), reverse=True)
    _, operation_code, matched_terms = matches[0]
    exact = any(normalize_text(term) == haystack for term in matched_terms)
    candidate = OperationDetectionCandidate(
        code=operation_code,
        kind="atomic",
        score=0.99 if exact else 0.94,
        matched_terms=tuple(matched_terms),
        exact=exact,
    )
    return OperationDetectionResult(
        operation_code=operation_code,
        operation_package_code=None,
        confidence_score=candidate.score,
        matched_terms=candidate.matched_terms,
        candidates=(candidate,),
        reason="legacy_operation_term_match",
    )


def detect_operation_detailed(
    item_text: str | None,
    payload: dict[str, Any] | None = None,
    *,
    project_variant_id: str | None = None,
    section_title: str | None = None,
    section_description: str | None = None,
    unit_code: str | None = None,
) -> OperationDetectionResult:
    """Detect an atomic operation or package with variant aliases and context."""
    payload = payload or _load_dictionary()
    if not project_variant_id:
        return _legacy_operation_detection(item_text or "", payload)
    catalog = _variant_operation_alias_catalog(str(project_variant_id))
    if not catalog:
        return _legacy_operation_detection(item_text or "", payload)

    item_haystack = normalize_text(item_text or "")
    context_haystack = normalize_text(" ".join(part for part in (section_title, section_description) if part))
    tokens = item_haystack.split()
    if not item_haystack:
        return OperationDetectionResult(None, None, None, ())
    override = _tz_operation_detection_override(item_text or "", item_haystack)
    if override is not None:
        return override

    policy = catalog.get("alias_policy") or {}
    exact_bonus = float(policy.get("exact_phrase_bonus", 0.07))
    ambiguity_delta = float(policy.get("ambiguity_delta", 0.035))
    atomic_bonus = float(policy.get("atomic_explicit_bonus", 0.06))
    package_penalty = float(policy.get("package_generic_penalty", 0.05))
    aggregate: dict[str, dict[str, Any]] = {}
    multi_candidates: list[dict[str, Any]] = []

    def add_candidate(
        code: str,
        *,
        kind: str,
        score: float,
        matched_term: str,
        source: str,
        stage_numbers: set[str] | None = None,
        exact: bool = False,
        context_gate_matched: bool = False,
    ) -> None:
        if not code:
            return
        current = aggregate.get(code)
        data = {
            "code": code,
            "kind": kind,
            "score": min(1.0, score),
            "matched_terms": {matched_term} if matched_term else set(),
            "sources": {source},
            "stage_numbers": set(stage_numbers or set()),
            "explicit_stage_numbers": (
                set(stage_numbers or set()) if source.startswith("variant_alias") else set()
            ),
            "exact": exact,
            "context_gate_matched": context_gate_matched,
        }
        if current is None:
            aggregate[code] = data
            return
        current["score"] = max(float(current["score"]), min(1.0, score))
        current["matched_terms"].update(data["matched_terms"])
        current["sources"].update(data["sources"])
        current["stage_numbers"].update(data["stage_numbers"])
        current["explicit_stage_numbers"].update(data["explicit_stage_numbers"])
        current["exact"] = bool(current["exact"] or exact)
        current["context_gate_matched"] = bool(
            current["context_gate_matched"] or context_gate_matched
        )

    # Common dictionary terms remain available, but variant-specific aliases win.
    common_policy = _operation_resolution_policy(payload)
    common_metadata = common_policy.get("operation_metadata") or {}
    for operation_code, terms in (common_policy.get("operations") or {}).items():
        if not isinstance(terms, list):
            continue
        operation_kind = str((common_metadata.get(operation_code) or {}).get("kind") or "atomic")
        for term in terms:
            matched, exact = _operation_term_match(str(term), item_haystack, tokens)
            if matched:
                add_candidate(
                    str(operation_code),
                    kind=operation_kind,
                    score=0.78 + (exact_bonus if exact else 0.0),
                    matched_term=str(term),
                    source="dictionary_operation_terms",
                    exact=exact,
                )

    for code, definition in catalog.get("operations", {}).items():
        if not isinstance(definition, dict):
            continue
        metadata = definition.get("metadata") or {}
        gate_definition = {**metadata, **{key: definition.get(key) for key in (
            "required_terms_any", "required_terms_all", "excluded_terms", "requires_context"
        ) if definition.get(key) is not None}}
        allowed, gate_matched = _operation_context_gate(
            gate_definition,
            item_haystack=item_haystack,
            context_haystack=context_haystack,
        )
        if not allowed:
            continue
        stage_numbers = set(catalog.get("operation_to_stages", {}).get(str(code), set()))
        terms = [str(term) for term in (definition.get("terms") or []) if term]
        title = str(definition.get("title") or "")
        if title:
            terms.append(title)
        for term in terms:
            matched, exact = _operation_term_match(term, item_haystack, tokens)
            if not matched:
                continue
            specificity = min(0.08, len(normalize_text(term)) / 250.0)
            add_candidate(
                str(code),
                kind="atomic",
                score=0.82 + specificity + (exact_bonus if exact else 0.0) + (0.03 if gate_matched else 0.0),
                matched_term=term,
                source="variant_operation_terms",
                stage_numbers=stage_numbers,
                exact=exact,
                context_gate_matched=gate_matched,
            )

    for code, package in catalog.get("packages", {}).items():
        if not isinstance(package, dict):
            continue
        allowed, gate_matched = _operation_context_gate(
            package,
            item_haystack=item_haystack,
            context_haystack=context_haystack,
        )
        if not allowed:
            continue
        stage_numbers = set(catalog.get("package_to_stages", {}).get(str(code), set()))
        terms = [str(term) for term in (package.get("terms") or []) if term]
        if package.get("title"):
            terms.append(str(package["title"]))
        for term in terms:
            matched, exact = _operation_term_match(term, item_haystack, tokens)
            if matched:
                add_candidate(
                    str(code),
                    kind="package",
                    score=0.84 + (exact_bonus if exact else 0.0) + (0.03 if gate_matched else 0.0),
                    matched_term=term,
                    source="variant_package_terms",
                    stage_numbers=stage_numbers,
                    exact=exact,
                    context_gate_matched=gate_matched,
                )

    generic_labels = {
        "монтаж", "кладка", "подготовка", "армирование", "бетонирование",
        "крепление", "доборы", "пирог", "подача", "геодезия",
    }
    for group in catalog.get("alias_groups", []):
        allowed, group_gate_matched = _operation_context_gate(
            group,
            item_haystack=item_haystack,
            context_haystack=context_haystack,
        )
        if not allowed:
            continue
        terms: list[tuple[str, float]] = []
        base_weight = float(group.get("weight") or policy.get("default_alias_weight", 0.92))
        for raw_alias in group.get("aliases") or []:
            if isinstance(raw_alias, dict):
                alias_text = str(raw_alias.get("text") or "")
                alias_weight = float(raw_alias.get("weight") or base_weight)
            else:
                alias_text = str(raw_alias or "")
                alias_weight = base_weight
            if alias_text:
                terms.append((alias_text, alias_weight))
        label = str(group.get("label") or "")
        if label and normalize_text(label) not in generic_labels and len(normalize_text(label)) >= 8:
            terms.append((label, max(0.82, base_weight - 0.04)))

        for alias_text, alias_weight in terms:
            matched, exact = _operation_term_match(alias_text, item_haystack, tokens)
            if not matched:
                continue
            alias_score = min(1.0, alias_weight + (exact_bonus if exact else 0.0))
            target_codes = tuple(str(code) for code in (group.get("target_codes") or []) if code)
            stage_number = str(group.get("stage_number") or "")
            stage_numbers = {stage_number} if stage_number else set()
            if str(group.get("target_kind") or "operation") == "operation" and len(target_codes) == 1:
                code = target_codes[0]
                kind = "package" if code in catalog.get("packages", {}) else "atomic"
                add_candidate(
                    code,
                    kind=kind,
                    score=alias_score,
                    matched_term=alias_text,
                    source=f"variant_alias:{group.get('source_id')}",
                    stage_numbers=stage_numbers,
                    exact=exact,
                    context_gate_matched=group_gate_matched,
                )
                continue

            direct_targets: list[tuple[str, str, bool]] = []
            for target_code in target_codes:
                target_def = catalog.get("operations", {}).get(target_code)
                target_kind = "atomic"
                if target_def is None:
                    target_def = catalog.get("packages", {}).get(target_code)
                    target_kind = "package"
                if not isinstance(target_def, dict):
                    continue
                target_gate, target_gate_matched = _operation_context_gate(
                    target_def.get("metadata") or target_def,
                    item_haystack=item_haystack,
                    context_haystack=context_haystack,
                )
                if not target_gate:
                    continue
                target_terms = [str(value) for value in (target_def.get("terms") or []) if value]
                if target_def.get("title"):
                    target_terms.append(str(target_def["title"]))
                target_matched = any(_operation_term_match(term, item_haystack, tokens)[0] for term in target_terms)
                if target_matched or target_gate_matched:
                    direct_targets.append((target_code, target_kind, target_gate_matched))

            if len(direct_targets) == 1 and not bool(group.get("requires_disambiguation")):
                target_code, target_kind, target_gate_matched = direct_targets[0]
                add_candidate(
                    target_code,
                    kind=target_kind,
                    score=min(1.0, alias_score + 0.025),
                    matched_term=alias_text,
                    source=f"variant_alias_resolved:{group.get('source_id')}",
                    stage_numbers=stage_numbers,
                    exact=exact,
                    context_gate_matched=target_gate_matched,
                )
            elif len(direct_targets) == 1 and direct_targets[0][2]:
                target_code, target_kind, target_gate_matched = direct_targets[0]
                add_candidate(
                    target_code,
                    kind=target_kind,
                    score=min(1.0, alias_score + 0.025),
                    matched_term=alias_text,
                    source=f"variant_alias_resolved:{group.get('source_id')}",
                    stage_numbers=stage_numbers,
                    exact=exact,
                    context_gate_matched=target_gate_matched,
                )
            else:
                multi_candidates.append(
                    {
                        "score": alias_score,
                        "matched_term": alias_text,
                        "source": f"variant_alias_multi:{group.get('source_id')}",
                        "stage_numbers": stage_numbers,
                        "target_codes": target_codes,
                        "exact": exact,
                    }
                )

    # An explicit row listing several atomic operations is represented by an existing package only.
    atomic_high = [
        value for value in aggregate.values()
        if value["kind"] == "atomic" and float(value["score"]) >= 0.88
    ]
    # A slash inside a material alternative (for example ``металл/брус``)
    # is not evidence that one estimate row contains several operations.
    conjunction = bool(re.search(r"(?:,|;|\+|\s/\s|\bи\b)", item_haystack))
    if conjunction and len(atomic_high) >= 2:
        atomic_codes = {str(value["code"]) for value in atomic_high}
        preferred_stage_numbers = set().union(*(value["stage_numbers"] for value in atomic_high))
        covering_package = _find_covering_package(catalog, atomic_codes, preferred_stage_numbers)
        if covering_package:
            add_candidate(
                covering_package,
                kind="package",
                score=0.995,
                matched_term=item_text or "",
                source="explicit_multi_operation_package",
                stage_numbers=set(catalog.get("package_to_stages", {}).get(covering_package, set())),
                exact=True,
            )
        elif len(atomic_codes) >= 2:
            multi_candidates.append(
                {
                    "score": 0.985,
                    "matched_term": item_text or "",
                    "source": "explicit_multi_operation_without_package",
                    "stage_numbers": preferred_stage_numbers,
                    "target_codes": tuple(sorted(atomic_codes)),
                    "exact": True,
                }
            )

    # A package object plus several explicit package actions is a deliberate
    # complex row, not an ambiguity between its atomic children.
    package_action_count = sum(
        1
        for stem in ("опалуб", "армир", "бетон", "распалуб", "вибр", "гидроизоляц", "утепл")
        if stem in item_haystack
    )
    if conjunction and package_action_count >= 2:
        for value in aggregate.values():
            if value["kind"] == "package" and float(value["score"]) >= 0.8:
                value["score"] = max(float(value["score"]), 0.995)
                value["sources"].add("explicit_package_object_with_actions")

    candidates: list[OperationDetectionCandidate] = []
    for value in aggregate.values():
        score = float(value["score"])
        if value["kind"] == "atomic" and value["exact"]:
            score = min(1.0, score + atomic_bonus)
        if value["kind"] == "package" and not value["exact"]:
            score = max(0.0, score - package_penalty)
        effective_stage_numbers = value.get("explicit_stage_numbers") or value["stage_numbers"]
        stage_numbers = tuple(sorted(effective_stage_numbers))
        candidates.append(
            OperationDetectionCandidate(
                code=str(value["code"]),
                kind=str(value["kind"]),
                score=score,
                matched_terms=tuple(sorted(value["matched_terms"])),
                source="+".join(sorted(value["sources"])),
                stage_numbers=stage_numbers,
                exact=bool(value["exact"]),
                context_gate_matched=bool(value.get("context_gate_matched")),
            )
        )
    for multi in multi_candidates:
        candidates.append(
            OperationDetectionCandidate(
                code=None,
                kind="multi_operation",
                score=float(multi["score"]),
                matched_terms=(str(multi["matched_term"]),),
                source=str(multi["source"]),
                stage_numbers=tuple(sorted(multi["stage_numbers"])),
                target_codes=tuple(multi["target_codes"]),
                exact=bool(multi["exact"]),
                context_gate_matched=False,
            )
        )

    if not candidates:
        return OperationDetectionResult(None, None, None, (), reason="no_operation_match")
    candidates.sort(
        key=lambda item: (float(item.score), item.exact, len(" ".join(item.matched_terms))),
        reverse=True,
    )
    top = candidates[0]
    exact_disambiguation = next(
        (
            candidate for candidate in candidates
            if candidate.kind == "multi_operation"
            and candidate.exact
            and candidate.score >= 0.85
            and top.code in set(candidate.target_codes)
        ),
        None,
    )
    if (
        exact_disambiguation is not None
        and top.kind != "package"
        and not top.context_gate_matched
        and top.score - exact_disambiguation.score <= 0.11
    ):
        top = exact_disambiguation
    if top.kind == "multi_operation":
        preferred_stage = top.stage_numbers[0] if len(top.stage_numbers) == 1 else None
        return OperationDetectionResult(
            operation_code=None,
            operation_package_code=None,
            confidence_score=top.score,
            matched_terms=top.matched_terms,
            candidates=tuple(candidates[:10]),
            needs_review=True,
            reason=str(policy.get("multi_operation_without_package_reason") or "multi_operation_row_requires_package_or_split"),
            preferred_stage_number=preferred_stage,
            multi_operation_codes=top.target_codes,
        )

    second = next((item for item in candidates[1:] if item.code != top.code), None)
    # Required context is a stronger discriminator than a score tie. This is
    # important for phrases that exist in several construction sections, such
    # as slab reinforcement or facade-panel sealing.
    if (
        second is not None
        and second.context_gate_matched
        and not top.context_gate_matched
        and top.score - second.score < ambiguity_delta
    ):
        top, second = second, top
    if second is not None and top.score - second.score < ambiguity_delta and second.score >= 0.84:
        # Explicit atomic wording is allowed to beat a generic package wording.
        # A candidate whose required context was satisfied is also allowed to
        # beat an otherwise equal generic phrase (for example facade sealing
        # versus thermal-panel sealing).
        context_resolved = top.context_gate_matched and not second.context_gate_matched
        if not context_resolved and not (top.kind == "atomic" and top.exact and second.kind == "package" and not second.exact):
            multi_peer = second if second.kind == "multi_operation" else (top if top.kind == "multi_operation" else None)
            stage_numbers = (
                multi_peer.stage_numbers
                if multi_peer is not None and len(multi_peer.stage_numbers) == 1
                else tuple(sorted(set(top.stage_numbers) | set(second.stage_numbers)))
            )
            preferred_stage = stage_numbers[0] if len(stage_numbers) == 1 else None
            multi_codes = (
                multi_peer.target_codes
                if multi_peer is not None and multi_peer.target_codes
                else tuple(code for code in (top.code, second.code) if code)
            )
            return OperationDetectionResult(
                operation_code=None,
                operation_package_code=None,
                confidence_score=top.score,
                matched_terms=top.matched_terms,
                candidates=tuple(candidates[:10]),
                needs_review=True,
                reason=str(policy.get("ambiguous_operation_reason") or "work_operation_ambiguous"),
                preferred_stage_number=preferred_stage,
                multi_operation_codes=multi_codes,
            )

    preferred_stage = top.stage_numbers[0] if len(top.stage_numbers) == 1 else None
    package_code = top.code if top.kind == "package" else None
    preferred_option = _preferred_option_for_operation(
        catalog,
        stage_number=preferred_stage,
        operation_code=top.code if top.kind == "atomic" else None,
        package_code=package_code,
        item_haystack=item_haystack,
    )
    return OperationDetectionResult(
        operation_code=top.code,
        operation_package_code=package_code,
        confidence_score=top.score,
        matched_terms=top.matched_terms,
        candidates=tuple(candidates[:10]),
        needs_review=False,
        reason=("operation_package_match" if package_code else "variant_operation_alias_match"),
        preferred_stage_number=preferred_stage,
        preferred_stage_option_id=preferred_option,
    )


def detect_operation(
    item_text: str | None,
    payload: dict[str, Any] | None = None,
    *,
    project_variant_id: str | None = None,
    section_title: str | None = None,
    section_description: str | None = None,
    unit_code: str | None = None,
) -> tuple[str | None, float | None, list[str]]:
    """Backward-compatible wrapper around the detailed operation detector."""
    result = detect_operation_detailed(
        item_text,
        payload,
        project_variant_id=project_variant_id,
        section_title=section_title,
        section_description=section_description,
        unit_code=unit_code,
    )
    return result.operation_code, result.confidence_score, list(result.matched_terms)


def _apply_operation_detection(
    result: ClassificationResult,
    detection: OperationDetectionResult,
) -> ClassificationResult:
    needs_review = bool(result.needs_review or detection.needs_review)
    reason = result.reason
    confidence = result.confidence
    if detection.needs_review and not result.needs_review:
        reason = detection.reason or reason
        confidence = "low"
    return replace(
        result,
        needs_review=needs_review,
        reason=reason,
        confidence=confidence,
        operation_code=detection.operation_code,
        operation_package_code=detection.operation_package_code,
        operation_confidence_score=detection.confidence_score,
        operation_candidates=tuple(item.as_dict() for item in detection.candidates),
        operation_detection_reason=detection.reason,
        operation_needs_review=detection.needs_review,
        operation_multi_codes=detection.multi_operation_codes,
        preferred_stage_number=detection.preferred_stage_number or result.preferred_stage_number,
        preferred_stage_option_id=detection.preferred_stage_option_id,
    )

def _merge_object_candidate(
    target: dict[str, dict[str, Any]],
    *,
    code: str,
    source: str,
    matched_terms: list[str],
    confidence_score: float,
) -> None:
    if not code:
        return
    current = target.get(code)
    evidence = {
        "source": source,
        "matched_terms": list(matched_terms),
        "confidence_score": confidence_score,
    }
    if current is None:
        target[code] = {
            "object_scope_code": code,
            "source": source,
            "matched_terms": list(matched_terms),
            "confidence_score": confidence_score,
            "evidence": [evidence],
        }
        return
    current.setdefault("evidence", []).append(evidence)
    current["confidence_score"] = max(float(current.get("confidence_score") or 0), confidence_score)
    for term in matched_terms:
        if term not in current.setdefault("matched_terms", []):
            current["matched_terms"].append(term)
    if confidence_score >= float(current.get("confidence_score") or 0):
        current["source"] = source


def detect_section_object_candidates(
    *,
    item_text: str | None = None,
    section_title: str | None = None,
    section_description: str | None = None,
    supplied_candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return all object candidates without collapsing a mixed-object block."""
    payload = payload or _load_dictionary()
    objects = (_operation_resolution_policy(payload).get("objects") or {})
    merged: dict[str, dict[str, Any]] = {}

    for candidate in supplied_candidates or ():
        if not isinstance(candidate, dict):
            continue
        code = str(candidate.get("object_scope_code") or "").strip()
        if not code:
            continue
        _merge_object_candidate(
            merged,
            code=code,
            source=str(candidate.get("source") or "supplied"),
            matched_terms=list(candidate.get("matched_terms") or []),
            confidence_score=float(candidate.get("confidence_score") or 0.8),
        )

    sources = (
        ("explicit_row_object", item_text, "title_terms", 1.0),
        ("section_title", section_title, "title_terms", 0.96),
        ("section_description", section_description, "description_terms", 0.92),
    )
    for source, raw_text, term_field, confidence in sources:
        haystack = normalize_text(raw_text or "")
        if not haystack:
            continue
        hay_tokens = haystack.split()
        for object_code, object_def in objects.items():
            if not isinstance(object_def, dict):
                continue
            terms = [str(term) for term in (object_def.get(term_field) or [])]
            matched = _match_terms(terms, haystack, hay_tokens)
            if matched:
                _merge_object_candidate(
                    merged,
                    code=str(object_code),
                    source=source,
                    matched_terms=matched,
                    confidence_score=confidence,
                )
    return sorted(
        merged.values(),
        key=lambda item: float(item.get("confidence_score") or 0),
        reverse=True,
    )


def _find_section_and_subtype(
    payload: dict[str, Any],
    section_id: str,
    subtype_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for section_def in payload.get("sections") or []:
        if not isinstance(section_def, dict) or str(section_def.get("id") or "") != section_id:
            continue
        for subtype_def in section_def.get("subtypes") or []:
            if isinstance(subtype_def, dict) and str(subtype_def.get("id") or "") == subtype_id:
                return section_def, subtype_def
        return section_def, None
    return None, None


def _contextual_resolution_result(
    *,
    name: str,
    section_title: str | None,
    section_description: str | None,
    supplied_candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    operation_hint: str | None,
    resolved_role: str,
    payload: dict[str, Any],
    normalized_pairs: frozenset[tuple[str, str]] | None,
    allowed_section_ids: frozenset[str] | None,
    scope_name: str,
    scope_fields: dict[str, Any],
    version: str,
    thresholds: dict[str, Any],
    operation_detection: OperationDetectionResult | None = None,
) -> ClassificationResult | None:
    if resolved_role != "work":
        return None

    operation_detection = operation_detection or detect_operation_detailed(name, payload)
    operation_code = operation_hint or operation_detection.operation_code
    operation_confidence = operation_detection.confidence_score
    operation_terms = list(operation_detection.matched_terms)
    if not operation_code:
        return None

    object_candidates = detect_section_object_candidates(
        item_text=name,
        section_title=section_title,
        section_description=section_description,
        supplied_candidates=supplied_candidates,
        payload=payload,
    )
    candidate_codes = {
        str(item.get("object_scope_code") or "")
        for item in object_candidates
        if item.get("object_scope_code")
    }

    matching_rules: list[dict[str, Any]] = []
    for rule in (_operation_resolution_policy(payload).get("rules") or []):
        if not isinstance(rule, dict) or str(rule.get("operation") or "") != operation_code:
            continue
        object_code = str(rule.get("object") or "")
        if object_code != "*" and object_code not in candidate_codes:
            continue
        section_id = str(rule.get("section_id") or "")
        subtype_id = str(rule.get("subtype_id") or "")
        if not section_id or not subtype_id:
            continue
        if allowed_section_ids is not None and section_id not in allowed_section_ids:
            continue
        if normalized_pairs is not None and (section_id, subtype_id) not in normalized_pairs:
            continue
        matching_rules.append(rule)

    if not matching_rules:
        return None

    unique_outputs = {
        (
            str(rule.get("section_id") or ""),
            str(rule.get("subtype_id") or ""),
            str(rule.get("preferred_stage_number") or ""),
        )
        for rule in matching_rules
    }
    if len(unique_outputs) != 1:
        return None

    selected_rule = next(
        (rule for rule in matching_rules if str(rule.get("object") or "") != "*"),
        matching_rules[0],
    )
    section_id = str(selected_rule.get("section_id") or "")
    subtype_id = str(selected_rule.get("subtype_id") or "")
    section_def, subtype_def = _find_section_and_subtype(payload, section_id, subtype_id)
    if section_def is None or subtype_def is None:
        return None

    selected_object = str(selected_rule.get("object") or "")
    if selected_object == "*":
        selected_object = None
    selected_candidate = next(
        (
            item for item in object_candidates
            if str(item.get("object_scope_code") or "") == selected_object
        ),
        None,
    )
    explicit_object = bool(
        selected_candidate and str(selected_candidate.get("source") or "") == "explicit_row_object"
    )
    auto_min = int(thresholds.get("auto_accept_min_score", 9))
    score = auto_min + 10
    subtype_code = f"{section_id}/{subtype_id}"
    matched_terms = {
        "operation": operation_terms or [operation_code],
        "operation_object_resolution": [
            f"{operation_code} × {selected_object or '*'} → {subtype_code}"
        ],
    }
    if selected_candidate:
        matched_terms["object_context"] = list(selected_candidate.get("matched_terms") or [])

    candidate = ClassificationCandidate(
        rank=1,
        stage="subtype",
        section_code=section_id,
        section_name=str(section_def.get("title") or ""),
        subtype_code=subtype_code,
        subtype_name=str(subtype_def.get("title") or subtype_id),
        score=score,
        section_score=score,
        subtype_score=score,
        delta_to_next=score,
        confidence="high",
        needs_review=False,
        source="operation_object_resolution",
        matched_terms=matched_terms,
        reason="deterministic_operation_object_rule",
    )
    return ClassificationResult(
        section_code=section_id,
        section_name=str(section_def.get("title") or ""),
        subtype_code=subtype_code,
        subtype_name=str(subtype_def.get("title") or subtype_id),
        score=score,
        confidence="high",
        needs_review=False,
        source="operation_object_resolution",
        matched_terms=matched_terms,
        candidates=[candidate],
        related_sections=[],
        reason="deterministic_operation_object_rule",
        dictionary_version=version,
        row_role=resolved_role,
        operation_code=operation_code,
        operation_package_code=operation_detection.operation_package_code,
        operation_confidence_score=operation_confidence or 0.9,
        operation_candidates=tuple(item.as_dict() for item in operation_detection.candidates),
        operation_detection_reason=operation_detection.reason,
        operation_needs_review=operation_detection.needs_review,
        operation_multi_codes=operation_detection.multi_operation_codes,
        preferred_stage_number=(
            operation_detection.preferred_stage_number
            or (str(selected_rule.get("preferred_stage_number") or "") or None)
        ),
        preferred_stage_option_id=operation_detection.preferred_stage_option_id,
        section_object_candidates=tuple(object_candidates),
        selected_object_scope_code=selected_object,
        object_scope_confidence_score=(
            float(selected_candidate.get("confidence_score") or 0)
            if selected_candidate else None
        ),
        object_scope_source=(
            str(selected_candidate.get("source") or "")
            if selected_candidate else "wildcard_operation_rule"
        ),
        context_override_blocked=explicit_object,
        context_override_reason=(
            "explicit_row_object_priority" if explicit_object else None
        ),
        **scope_fields,
    )


def classify_work(
    name: str,
    section: str | None = None,
    *,
    section_title: str | None = None,
    section_description: str | None = None,
    section_object_candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    operation_hint: str | None = None,
    row_role: str | None = None,
    candidate_sections: set[str] | frozenset[str] | None = None,
    candidate_pairs: set[tuple[str, str]] | frozenset[tuple[str, str]] | None = None,
    scope_name: str = "global",
    scope_estimate_type_id: str | None = None,
    scope_project_variant_id: str | None = None,
    fallback_used: bool = False,
) -> ClassificationResult:
    payload = _load_dictionary()
    weights = (payload.get("scoring") or {}).get("weights") or {}
    thresholds = (payload.get("scoring") or {}).get("decision_thresholds") or {}
    effective_title = section_title if section_title is not None else section
    effective_description = section_description
    context_text = " ".join(
        part for part in (effective_title, effective_description) if part
    )
    text = " ".join(part for part in (name, context_text) if part)
    item_haystack = normalize_text(name)
    section_haystack = normalize_text(context_text)
    haystack = normalize_text(text)
    hay_tokens = haystack.split()
    version = dictionary_version(payload)
    resolved_role = row_role or classify_row_role(name, context_text, payload=payload)
    operation_detection = detect_operation_detailed(
        name,
        payload,
        project_variant_id=scope_project_variant_id,
        section_title=effective_title,
        section_description=effective_description,
    )

    normalized_pairs: frozenset[tuple[str, str]] | None = None
    if candidate_pairs is not None:
        normalized_pairs = frozenset(
            (str(section_id), str(subtype_id))
            for section_id, subtype_id in candidate_pairs
            if section_id and subtype_id
        )
    allowed_section_ids: frozenset[str] | None = None
    if candidate_sections is not None:
        allowed_section_ids = frozenset(str(section_id) for section_id in candidate_sections if section_id)
    if normalized_pairs is not None:
        pair_sections = frozenset(section_id for section_id, _ in normalized_pairs)
        allowed_section_ids = pair_sections if allowed_section_ids is None else allowed_section_ids & pair_sections

    all_sections = [section for section in (payload.get("sections") or []) if isinstance(section, dict)]
    sections = [
        section_def
        for section_def in all_sections
        if allowed_section_ids is None or str(section_def.get("id") or "") in allowed_section_ids
    ]
    pairs_by_section: dict[str, frozenset[str]] = {}
    if normalized_pairs is not None:
        for section_id in {pair[0] for pair in normalized_pairs}:
            pairs_by_section[section_id] = frozenset(
                subtype_id for pair_section, subtype_id in normalized_pairs if pair_section == section_id
            )

    pre_object_priority_pair = _explicit_object_priority_pair(
        item_haystack,
        section_haystack,
    )
    demolition_priority = False
    priority_section = pre_object_priority_pair[0] if pre_object_priority_pair else None
    if _has_demolition_intent(haystack, hay_tokens) and priority_section in {None, "reconstruction_works"}:
        reconstruction_allowed = allowed_section_ids is None or "reconstruction_works" in allowed_section_ids
        allowed_demolition_ids = _DEMOLITION_SUBTYPE_IDS
        if normalized_pairs is not None:
            allowed_demolition_ids = frozenset(
                subtype_id
                for section_id, subtype_id in normalized_pairs
                if section_id == "reconstruction_works" and subtype_id in _DEMOLITION_SUBTYPE_IDS
            )
        if reconstruction_allowed and allowed_demolition_ids:
            sections = [
                section_def
                for section_def in sections
                if str(section_def.get("id") or "") == "reconstruction_works"
            ]
            pairs_by_section["reconstruction_works"] = allowed_demolition_ids
            demolition_priority = bool(sections)

    sections_by_id = {str(section_def["id"]): section_def for section_def in sections}
    scope_fields = {
        "classification_scope": scope_name,
        "scope_estimate_type_id": scope_estimate_type_id,
        "scope_project_variant_id": scope_project_variant_id,
        "scope_candidate_sections": len(sections_by_id),
        "scope_candidate_pairs": len(normalized_pairs or ()),
        "fallback_used": fallback_used,
    }

    if not haystack:
        return ClassificationResult(
            section_code=None,
            section_name=None,
            subtype_code=UNKNOWN_SUBTYPE_CODE,
            subtype_name=UNKNOWN_SUBTYPE_NAME,
            score=0,
            confidence="low",
            needs_review=True,
            source=scope_name,
            matched_terms={},
            candidates=[],
            related_sections=[],
            reason="empty_name",
            dictionary_version=version,
            row_role=resolved_role,
            **scope_fields,
        )

    if resolved_role in service_row_roles(payload):
        return ClassificationResult(
            section_code=None,
            section_name=None,
            subtype_code=UNKNOWN_SUBTYPE_CODE,
            subtype_name=SERVICE_ROW_SUBTYPE_NAME,
            score=0,
            confidence="low",
            needs_review=False,
            source=f"row_role_{resolved_role}",
            matched_terms={"row_role": [resolved_role]},
            candidates=[],
            related_sections=[],
            reason="row_role_skip",
            dictionary_version=version,
            row_role=resolved_role,
            **scope_fields,
        )

    if not sections_by_id:
        return ClassificationResult(
            section_code=None,
            section_name=None,
            subtype_code=UNKNOWN_SUBTYPE_CODE,
            subtype_name=UNKNOWN_SUBTYPE_NAME,
            score=0,
            confidence="low",
            needs_review=True,
            source=scope_name,
            matched_terms={},
            candidates=[],
            related_sections=[],
            reason="empty_candidate_scope",
            dictionary_version=version,
            row_role=resolved_role,
            **scope_fields,
        )

    contextual_result = _contextual_resolution_result(
        name=name,
        section_title=effective_title,
        section_description=effective_description,
        supplied_candidates=section_object_candidates,
        operation_hint=operation_hint,
        resolved_role=resolved_role,
        payload=payload,
        normalized_pairs=normalized_pairs,
        allowed_section_ids=allowed_section_ids,
        scope_name=scope_name,
        scope_fields=scope_fields,
        version=version,
        thresholds=thresholds,
        operation_detection=operation_detection,
    )
    if contextual_result is not None:
        return _apply_operation_detection(contextual_result, operation_detection)

    object_priority_pair = pre_object_priority_pair
    if object_priority_pair is not None:
        object_section, object_subtype, _, _ = object_priority_pair
        pair_allowed = (
            object_section in sections_by_id
            and (
                normalized_pairs is None
                or (object_section, object_subtype) in normalized_pairs
            )
        )
        if pair_allowed:
            object_result = _explicit_object_priority_result(
                pair=object_priority_pair,
                sections_by_id=sections_by_id,
                resolved_role=resolved_role,
                version=version,
                scope_name=scope_name,
                scope_fields=scope_fields,
                thresholds=thresholds,
            )
            if object_result is not None:
                return _apply_operation_detection(object_result, operation_detection)

    section_scores: dict[str, int] = {}
    section_matches: dict[str, dict[str, list[str]]] = {}
    for sec in sections:
        section_id = str(sec["id"])
        allowed_subtypes = pairs_by_section.get(section_id) if normalized_pairs is not None or demolition_priority else None
        score, matched = _score_section(sec, haystack, hay_tokens, weights)
        subtype_hint_score, subtype_hint_matches = _best_subtype_hint(
            sec,
            haystack,
            hay_tokens,
            weights,
            allowed_subtype_ids=allowed_subtypes,
        )
        if subtype_hint_score > 0:
            score += subtype_hint_score
            matched["subtype_hint_terms"] = [
                term
                for values in subtype_hint_matches.values()
                for term in values
            ]
        section_scores[section_id] = score
        section_matches[section_id] = matched

    profile_rules = _apply_estimate_profiles(
        section_scores, section_matches, haystack, hay_tokens, payload
    )
    conflict_rules = [] if demolition_priority else _apply_conflict_rules(
        sections_by_id, section_scores, section_matches, haystack, hay_tokens, payload
    )
    if "windows_doors" in section_scores and _match_terms(
        ["межкомнатная дверь", "дверной блок", "установка двери"],
        haystack,
        hay_tokens,
    ):
        section_scores["windows_doors"] += int(
            weights.get("conflict_prefer_boost", 4)
        ) + int(thresholds.get("min_delta_between_top_two", 3))
        section_matches.setdefault("windows_doors", {}).setdefault(
            "conflict_prefer_terms", []
        ).append("дверной блок")

    ranked_sections = sorted(
        (
            (section_id, score, section_matches.get(section_id) or {})
            for section_id, score in section_scores.items()
        ),
        key=lambda item: (item[1], -len(item[2].get("negative_terms") or [])),
        reverse=True,
    )
    ranked_sections = [item for item in ranked_sections if item[1] > 0]
    if not ranked_sections:
        return ClassificationResult(
            section_code=None,
            section_name=None,
            subtype_code=UNKNOWN_SUBTYPE_CODE,
            subtype_name=UNKNOWN_SUBTYPE_NAME,
            score=0,
            confidence="low",
            needs_review=True,
            source="demolition_priority" if demolition_priority else scope_name,
            matched_terms={"demolition_intent": ["detected"]} if demolition_priority else {},
            candidates=[],
            related_sections=[],
            reason="no_section_match",
            dictionary_version=version,
            row_role=resolved_role,
            **scope_fields,
        )

    section_candidates = _section_candidates(ranked_sections, sections_by_id, thresholds)
    winner_id, winner_score, winner_matches = ranked_sections[0]
    second_score = ranked_sections[1][1] if len(ranked_sections) > 1 else 0
    section_delta = winner_score - second_score
    auto_min = int(thresholds.get("auto_accept_min_score", 9))
    min_delta = int(thresholds.get("min_delta_between_top_two", 3))
    review_min = int(thresholds.get("review_min_score", 5))
    section_needs_review = winner_score < auto_min or section_delta < min_delta
    source = "demolition_priority" if demolition_priority else (
        scope_name if not section_needs_review else f"{scope_name}_review"
    )

    winning_section = sections_by_id[winner_id]
    allowed_winner_subtypes = pairs_by_section.get(winner_id) if normalized_pairs is not None or demolition_priority else None
    subtype_candidates, subtype_matches = _subtype_candidates(
        winning_section,
        winner_score,
        haystack,
        hay_tokens,
        weights,
        thresholds,
        payload,
        allowed_subtype_ids=allowed_winner_subtypes,
    )
    best_subtype = subtype_candidates[0] if subtype_candidates else None

    subtype_needs_review = best_subtype is None or best_subtype.needs_review
    needs_review = section_needs_review or subtype_needs_review or winner_score < review_min
    matched_terms: dict[str, list[str]] = {
        **winner_matches,
        **(subtype_matches or {}),
    }
    if demolition_priority:
        matched_terms["demolition_intent"] = _match_terms(
            list(_DEMOLITION_ACTION_TERMS), haystack, hay_tokens
        ) + _match_terms(list(_DEMOLITION_OBJECT_TERMS), haystack, hay_tokens)
    if profile_rules:
        matched_terms["estimate_profiles_applied"] = profile_rules
    if conflict_rules:
        matched_terms["conflict_rules_applied"] = conflict_rules
    related = _related_sections(winner_id, matched_terms, haystack, hay_tokens, payload)
    if best_subtype:
        for section_id in best_subtype.related_sections:
            if section_id not in related:
                related.append(section_id)

    if best_subtype and not subtype_needs_review:
        subtype_code = best_subtype.subtype_code or UNKNOWN_SUBTYPE_CODE
        subtype_name = best_subtype.subtype_name or UNKNOWN_SUBTYPE_NAME
        total_score = best_subtype.score
        subtype_delta = best_subtype.delta_to_next or 0
        reason = "demolition_priority" if demolition_priority else (
            "auto_accept" if not needs_review else "needs_review"
        )
    else:
        subtype_code = UNKNOWN_SUBTYPE_CODE
        subtype_name = UNKNOWN_SUBTYPE_NAME
        total_score = winner_score
        subtype_delta = 0
        reason = "subtype_ambiguous"

    confidence = _confidence(total_score, min(section_delta, subtype_delta), needs_review, thresholds)
    candidates = section_candidates + subtype_candidates
    detected_objects = detect_section_object_candidates(
        item_text=name,
        section_title=effective_title,
        section_description=effective_description,
        supplied_candidates=section_object_candidates,
        payload=payload,
    )
    result = ClassificationResult(
        section_code=winner_id,
        section_name=winning_section.get("title"),
        subtype_code=subtype_code,
        subtype_name=subtype_name,
        score=total_score,
        confidence=confidence,
        needs_review=needs_review,
        source=source,
        matched_terms=matched_terms,
        candidates=candidates,
        related_sections=related,
        reason=reason,
        dictionary_version=version,
        row_role=resolved_role,
        operation_code=operation_detection.operation_code,
        operation_package_code=operation_detection.operation_package_code,
        operation_confidence_score=operation_detection.confidence_score,
        operation_candidates=tuple(item.as_dict() for item in operation_detection.candidates),
        operation_detection_reason=operation_detection.reason,
        operation_needs_review=operation_detection.needs_review,
        operation_multi_codes=operation_detection.multi_operation_codes,
        preferred_stage_number=operation_detection.preferred_stage_number,
        preferred_stage_option_id=operation_detection.preferred_stage_option_id,
        section_object_candidates=tuple(detected_objects),
        **scope_fields,
    )
    return _apply_operation_detection(result, operation_detection)


def _scope_result_requires_fallback(result: ClassificationResult, review_min_score: int) -> bool:
    if result.reason in {
        "empty_candidate_scope",
        "no_section_match",
        "empty_name",
        "subtype_ambiguous",
        "scoped_subtype_rejected",
    }:
        return True
    if result.section_code is None:
        return True
    if result.needs_review:
        return True
    if not result.subtype_code or result.subtype_code == UNKNOWN_SUBTYPE_CODE:
        return True
    if int(result.score or 0) < review_min_score:
        return True
    subtype_candidates = [
        candidate for candidate in result.candidates
        if candidate.stage == "subtype" and candidate.subtype_code
    ]
    if subtype_candidates:
        best = subtype_candidates[0]
        if best.needs_review:
            return True
        if int(best.delta_to_next or 0) < int(
            ((_load_dictionary().get("scoring") or {}).get("decision_thresholds") or {}).get(
                "min_delta_between_top_two", 3
            )
        ):
            return True
    return False


def _scoped_rejection_reason(result: ClassificationResult, review_min_score: int) -> str:
    if result.reason in {"subtype_ambiguous", "no_section_match", "empty_candidate_scope"}:
        return result.reason
    if not result.subtype_code or result.subtype_code == UNKNOWN_SUBTYPE_CODE:
        return "scoped_subtype_unknown"
    if result.needs_review:
        return "scoped_result_needs_review"
    if int(result.score or 0) < review_min_score:
        return "scoped_score_below_review_min"
    return "scoped_subtype_rejected"


def _as_rejected_scoped_result(
    result: ClassificationResult,
    rejection_reason: str,
    *,
    global_candidate: str | None = None,
) -> ClassificationResult:
    matched = dict(result.matched_terms or {})
    matched.setdefault("scoped_rejection", []).append(rejection_reason)
    return replace(
        result,
        subtype_code=UNKNOWN_SUBTYPE_CODE,
        subtype_name=UNKNOWN_SUBTYPE_NAME,
        confidence="low",
        needs_review=True,
        source="scoped_rejected",
        matched_terms=matched,
        reason="scoped_subtype_rejected",
        scoped_rejection_reason=rejection_reason,
        scoped_candidate_subtype=(
            result.subtype_code if result.subtype_code != UNKNOWN_SUBTYPE_CODE else None
        ),
        global_candidate_subtype=global_candidate,
        global_fallback_accept_reason=None,
    )


def _global_result_is_safe(
    result: ClassificationResult,
    thresholds: dict[str, Any],
) -> tuple[bool, str]:
    if result.needs_review or result.subtype_code == UNKNOWN_SUBTYPE_CODE:
        return False, "global_result_needs_review"
    if int(result.score or 0) < int(thresholds.get("auto_accept_min_score", 9)):
        return False, "global_score_below_auto_accept"
    subtype_candidates = [
        candidate for candidate in result.candidates
        if candidate.stage == "subtype" and candidate.subtype_code
    ]
    if subtype_candidates and int(subtype_candidates[0].delta_to_next or 0) < int(
        thresholds.get("min_delta_between_top_two", 3)
    ):
        return False, "global_subtype_delta_too_small"
    matched = result.matched_terms or {}
    strong_evidence = bool(
        result.source == "object_priority"
        or result.object_priority_rule
        or matched.get("object_priority")
        or matched.get("action_object_pairs")
        or matched.get("operation_object_resolution")
        or matched.get("subtype_strong_terms")
        or matched.get("exact_strong_phrase")
    )
    if not strong_evidence:
        return False, "global_result_has_only_generic_terms"
    if matched.get("subtype_negative_terms") or result.object_conflicts:
        return False, "global_object_conflict"
    return True, "strong_global_object_or_phrase"


def _classification_blocker_result(
    *,
    reason: str,
    row_role: str | None,
    section_code: str | None = None,
    suggested_taxonomy_code: str | None = None,
    suggested_operation_code: str | None = None,
) -> ClassificationResult:
    payload = _load_dictionary()
    section_name = None
    if section_code:
        section = next((row for row in payload.get("sections", []) if row.get("id") == section_code), None)
        section_name = section.get("title") if section else None
    return ClassificationResult(
        section_code=section_code,
        section_name=section_name,
        subtype_code=UNKNOWN_SUBTYPE_CODE,
        subtype_name=UNKNOWN_SUBTYPE_NAME,
        score=0,
        confidence="low",
        needs_review=True,
        source="classification_blocker",
        matched_terms={"classification_blocker": [reason]},
        candidates=[],
        related_sections=[],
        reason=reason,
        dictionary_version=dictionary_version(payload),
        row_role=row_role or "work",
        classification_scope="classification_blocker",
        fallback_used=False,
        suggested_taxonomy_code=suggested_taxonomy_code,
        suggested_operation_code=suggested_operation_code,
    )


def classify_work_cascade(
    name: str,
    section: str | None = None,
    *,
    section_title: str | None = None,
    section_description: str | None = None,
    section_object_candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    operation_hint: str | None = None,
    row_role: str | None = None,
    variant_scope: TaxonomyScope | None = None,
    estimate_type_scope: TaxonomyScope | None = None,
    allow_global_fallback: bool = True,
) -> ClassificationResult:
    """Classify in variant → estimate type → controlled global fallback order."""
    work_text, section_context_text, source_context_text = build_rate_context_text(
        work_name=name,
        item_text=name,
        section_title=section_title,
        section_description=section_description,
        section_parent_context=section,
    )
    if has_internal_wall_insulation_exception(source_context_text):
        return _classification_blocker_result(
            reason="internal_wall_insulation_exception",
            row_role=row_role,
            section_code="insulation",
            suggested_taxonomy_code="insulation/internal_wall_insulation",
        )

    special_operation = resolve_special_masonry_operation(work_text, section_context_text)
    if special_operation == "brick_pillar_masonry":
        has_fence_context = _contains_any(source_context_text, (
            "забор", "огражден", "ограждён", "штакет", "ворот", "калитк", "благоустрой",
        ))
        has_building_context = _contains_any(source_context_text, (
            "здани", "каркас", "несущ", "колонна здания", "колонны здания",
        ))
        if not has_fence_context and not has_building_context:
            return _classification_blocker_result(
                reason="brick_pillar_object_not_resolved",
                row_role=row_role,
                suggested_operation_code="brick_pillar_masonry",
            )

    thresholds = ((_load_dictionary().get("scoring") or {}).get("decision_thresholds") or {})
    review_min = int(thresholds.get("review_min_score", 5))
    attempts: list[TaxonomyScope] = []
    if variant_scope is not None:
        attempts.append(variant_scope)
    if estimate_type_scope is not None:
        attempts.append(estimate_type_scope)

    scoped_results: list[ClassificationResult] = []
    rejection_reasons: list[str] = []
    for index, scope in enumerate(attempts):
        result = classify_work(
            name,
            section,
            section_title=section_title,
            section_description=section_description,
            section_object_candidates=section_object_candidates,
            operation_hint=operation_hint,
            row_role=row_role,
            candidate_sections=scope.allowed_sections,
            candidate_pairs=scope.allowed_pairs,
            scope_name=scope.name,
            scope_estimate_type_id=scope.estimate_type_id,
            scope_project_variant_id=(
                variant_scope.project_variant_id if variant_scope is not None
                else scope.project_variant_id
            ),
            fallback_used=index > 0,
        )
        scoped_results.append(result)
        if not _scope_result_requires_fallback(result, review_min):
            return result
        rejection_reasons.append(_scoped_rejection_reason(result, review_min))

    strongest_scoped = max(scoped_results, key=lambda item: int(item.score or 0)) if scoped_results else None
    strongest_reason = (
        rejection_reasons[scoped_results.index(strongest_scoped)]
        if strongest_scoped is not None
        else "no_scoped_result"
    )

    if not allow_global_fallback:
        if strongest_scoped is not None:
            return _as_rejected_scoped_result(strongest_scoped, strongest_reason)
        return ClassificationResult(
            section_code=None,
            section_name=None,
            subtype_code=UNKNOWN_SUBTYPE_CODE,
            subtype_name=UNKNOWN_SUBTYPE_NAME,
            score=0,
            confidence="low",
            needs_review=True,
            source="scoped_classification_unavailable",
            matched_terms={},
            candidates=[],
            related_sections=[],
            reason="no_scope_and_global_fallback_disabled",
            dictionary_version=dictionary_version(),
            row_role=row_role or "unknown",
            classification_scope="scoped_classification_unavailable",
            fallback_used=False,
            scoped_rejection_reason="no_scoped_result",
        )

    global_scope_name = "global_fallback" if scoped_results else "global_no_hierarchy"
    selected_scope = variant_scope or estimate_type_scope
    global_result = classify_work(
        name,
        section,
        section_title=section_title,
        section_description=section_description,
        section_object_candidates=section_object_candidates,
        operation_hint=operation_hint,
        row_role=row_role,
        scope_name=global_scope_name,
        scope_estimate_type_id=selected_scope.estimate_type_id if selected_scope else None,
        scope_project_variant_id=variant_scope.project_variant_id if variant_scope else None,
        fallback_used=bool(scoped_results),
    )
    safe, accept_reason = _global_result_is_safe(global_result, thresholds)
    if safe:
        return replace(
            global_result,
            scoped_rejection_reason=strongest_reason if strongest_scoped else None,
            scoped_candidate_subtype=(
                strongest_scoped.subtype_code
                if strongest_scoped and strongest_scoped.subtype_code != UNKNOWN_SUBTYPE_CODE
                else None
            ),
            global_candidate_subtype=global_result.subtype_code,
            global_fallback_accept_reason=accept_reason,
        )

    if strongest_scoped is not None:
        return _as_rejected_scoped_result(
            strongest_scoped,
            strongest_reason,
            global_candidate=global_result.subtype_code,
        )
    return replace(
        global_result,
        subtype_code=UNKNOWN_SUBTYPE_CODE,
        subtype_name=UNKNOWN_SUBTYPE_NAME,
        confidence="low",
        needs_review=True,
        source="global_rejected",
        reason="global_fallback_rejected",
        scoped_rejection_reason="no_scoped_result",
        global_candidate_subtype=global_result.subtype_code,
        global_fallback_accept_reason=None,
    )


def _classify_legacy_subtype(
    name: str,
    section: str | None,
    taxonomy: list[SubtypeDef],
) -> SubtypeMatch | None:
    haystack = " ".join(p for p in (name, section) if p).casefold()
    if not haystack.strip():
        return None

    best: SubtypeMatch | None = None
    best_longest = 0
    for sub in taxonomy:
        matched = [kw for kw in sub.keywords if kw in haystack]
        if not matched:
            continue
        score = len(matched)
        longest = max(len(kw) for kw in matched)
        if best is None or score > best.score or (
            score == best.score and longest > best_longest
        ):
            best = SubtypeMatch(
                macro_id=sub.macro_id, code=sub.code, name=sub.name, score=score
            )
            best_longest = longest
    return best


def classify_subtype(
    name: str,
    section: str | None,
    taxonomy: list[SubtypeDef],
) -> SubtypeMatch | None:
    """Backward-compatible subtype selector.

    CSV callers get the old keyword behavior. JSON callers get the canonical
    ``section/subtype`` code unless the classifier needs operator review.
    """
    if not any("/" in sub.code or sub.section_code for sub in taxonomy):
        return _classify_legacy_subtype(name, section, taxonomy)

    result = classify_work(name, section)
    if result.subtype_code == UNKNOWN_SUBTYPE_CODE:
        return None
    macro_id = 0
    for sub in taxonomy:
        if sub.code == result.subtype_code:
            macro_id = sub.macro_id
            break
    return SubtypeMatch(
        macro_id=macro_id,
        code=result.subtype_code,
        name=result.subtype_name,
        score=result.score,
        section_code=result.section_code,
        section_name=result.section_name,
        confidence=result.confidence,
        needs_review=result.needs_review,
    )


def build_precedence_dependencies(
    subtype_to_task_ids: dict[str, list[str]],
    precedence: list[PrecedenceEdge],
) -> list[tuple[str, str, int]]:
    """Build ``(successor_task_id, predecessor_task_id, lag_days)`` edges."""
    edges: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for edge in precedence:
        preds = subtype_to_task_ids.get(edge.predecessor_code)
        succs = subtype_to_task_ids.get(edge.successor_code)
        if not preds or not succs:
            continue
        predecessor_task_id = preds[-1]
        successor_task_id = succs[0]
        if predecessor_task_id == successor_task_id:
            continue
        key = (successor_task_id, predecessor_task_id)
        if key in seen:
            continue
        seen.add(key)
        edges.append((successor_task_id, predecessor_task_id, edge.lag_days))
    return edges
