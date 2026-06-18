"""Work taxonomy classification, hierarchy and precedence helpers.

``construction_work_dictionary_v6_4_draft.json`` is the canonical work
classifier. The CSV helper remains only for legacy callers.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkPrecedence, WorkSubtype


DICTIONARY_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "construction_work_dictionary_v6_4_draft.json"
)
DICTIONARY_SOURCE = "construction_work_dictionary_v6_4"
PROMPT_VERSION = "estimate-v6.4"
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
            # Legacy names kept until the UI/API is fully migrated.
            "subtype_code": self.subtype_code,
            "subtype_name": self.subtype_name,
            "macro_id": None,
        }


_taxonomy_cache: list[SubtypeDef] | None = None
_precedence_cache: list[PrecedenceEdge] | None = None


def clear_cache() -> None:
    """Reset DB-backed caches. Used by tests."""
    global _taxonomy_cache, _precedence_cache
    _taxonomy_cache = None
    _precedence_cache = None
    _load_dictionary.cache_clear()


@lru_cache(maxsize=1)
def _load_dictionary() -> dict[str, Any]:
    with open(DICTIONARY_FILE, encoding="utf-8") as fh:
        payload = json.load(fh)
    validate_dictionary_payload(payload)
    return payload


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
                    if option.get("autofill_enabled") and not (option.get("section_id") and option.get("subtype_id")):
                        errors.append(f"stage {stage_number} option {option.get('id')} autofill without subtype")
                    section_id = option.get("section_id")
                    subtype_id = option.get("subtype_id")
                    if section_id and subtype_id and (str(section_id), str(subtype_id)) not in subtypes_by_section:
                        errors.append(f"stage {stage_number} option {option.get('id')} invalid subtype {section_id}/{subtype_id}")
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
        "stage_role": stage.get("stage_role"),
        "stage_options_mode": stage.get("stage_options_mode") or "none",
        "stage_options": stage.get("stage_options") or [],
        "detail_lines": stage.get("detail_lines") or [],
        "occurrence_index": stage.get("occurrence_index"),
        "occurrence_label": stage.get("occurrence_label"),
        "autofill_enabled": bool(stage.get("autofill_enabled", False)),
        "primary_work_type": stage.get("primary_work_type") or None,
        "related_work_types": stage.get("related_work_types") or [],
    }


def _public_project_variant(variant: dict[str, Any], include_stages: bool) -> dict[str, Any]:
    stages = variant.get("stages") if isinstance(variant.get("stages"), list) else []
    item = {
        "id": str(variant.get("id") or ""),
        "number": str(variant.get("number") or ""),
        "title": str(variant.get("title") or ""),
        "stages_count": len(stages),
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
        {
            "number": str(variant.get("number") or ""),
            "id": str(variant.get("id") or ""),
            "title": str(variant.get("title") or ""),
            "stages_count": len(variant.get("stages") or []),
        }
        for variant in estimate_type.get("project_variants") or []
        if isinstance(variant, dict)
    ]


def get_project_variant_stages(estimate_type_id: str, project_variant_id: str) -> list[dict[str, Any]]:
    payload = _load_dictionary()
    estimate_type = _find_estimate_type(payload, estimate_type_id)
    variant = _find_project_variant(estimate_type, project_variant_id)
    return [
        _public_work_stage(stage)
        for stage in variant.get("stages") or []
        if isinstance(stage, dict)
    ]


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


def suggest_project_hierarchy_variants(
    texts: list[str],
    *,
    estimate_type_id: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Suggest top project hierarchy nodes without running stage-aware matching.

    This is intentionally broad and cheap: it scores only titles/detail lines from
    the selected scope, so import still requires the user to choose a variant
    before stage-aware classification is allowed.
    """
    payload = _load_dictionary()
    haystack = normalize_text(" ".join(texts[:100]))
    hay_tokens = haystack.split()
    estimate_types = _hierarchy_estimate_types(payload)
    type_scores: list[tuple[int, dict[str, Any], list[str]]] = []
    variant_scores: list[tuple[int, dict[str, Any], dict[str, Any], list[str]]] = []

    for estimate_type in estimate_types:
        type_terms = [estimate_type.get("title"), estimate_type.get("number"), estimate_type.get("id")]
        type_matches = _match_terms([str(term) for term in type_terms if term], haystack, hay_tokens)
        type_score = len(type_matches) * 3
        for variant in estimate_type.get("project_variants") or []:
            if not isinstance(variant, dict):
                continue
            variant_terms: list[str] = [
                str(variant.get("title") or ""),
                str(variant.get("number") or ""),
                str(variant.get("id") or ""),
            ]
            for stage in variant.get("stages") or []:
                if not isinstance(stage, dict):
                    continue
                variant_terms.append(str(stage.get("title") or ""))
                variant_terms.extend(str(line) for line in (stage.get("detail_lines") or [])[:3])
                for option in stage.get("stage_options") or []:
                    if isinstance(option, dict):
                        variant_terms.append(str(option.get("title") or ""))
            matches = _match_terms([term for term in variant_terms if term], haystack, hay_tokens)
            score = type_score + len(matches)
            variant_scores.append((score, estimate_type, variant, matches[:10]))
            if matches:
                type_score += min(len(matches), 5)
        type_scores.append((type_score, estimate_type, type_matches[:10]))

    type_scores.sort(key=lambda item: item[0], reverse=True)
    if estimate_type_id:
        try:
            selected_type = _find_estimate_type(payload, estimate_type_id)
        except ValueError:
            selected_type = None
        if selected_type:
            variant_scores = [
                item for item in variant_scores
                if str(item[1].get("id") or "") == str(selected_type.get("id") or "")
            ]
    variant_scores.sort(key=lambda item: item[0], reverse=True)
    return {
        "estimate_types": [
            {
                "id": str(item.get("id") or ""),
                "number": str(item.get("number") or ""),
                "title": str(item.get("title") or ""),
                "estimate_kind": legacy_estimate_kind_for_type(str(item.get("id") or "")),
                "score": score,
                "matched_terms": matches,
            }
            for score, item, matches in type_scores[:limit]
        ],
        "project_variants": [
            {
                "estimate_type_id": str(estimate_type.get("id") or ""),
                "estimate_type_number": str(estimate_type.get("number") or ""),
                "estimate_type_title": str(estimate_type.get("title") or ""),
                "id": str(variant.get("id") or ""),
                "number": str(variant.get("number") or ""),
                "title": str(variant.get("title") or ""),
                "stages_count": len(variant.get("stages") or []),
                "score": score,
                "matched_terms": matches,
            }
            for score, estimate_type, variant, matches in variant_scores[:limit]
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
        return _token_skeleton(token_stem) == _token_skeleton(hay_stem)
    return False


def _matched_token_is_negated(index: int, hay_tokens: list[str]) -> bool:
    return index > 0 and hay_tokens[index - 1] in _NEGATION_TOKENS


def _term_matches(term: str, haystack: str, hay_tokens: list[str] | None = None) -> bool:
    norm_term = normalize_text(term)
    if not norm_term:
        return False
    hay_tokens = hay_tokens or haystack.split()
    term_tokens = [t for t in norm_term.split() if t]
    if not term_tokens:
        return False
    if len(term_tokens) > 1:
        pattern = rf"(?<!\w){re.escape(norm_term)}(?!\w)"
        if re.search(pattern, haystack):
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
    hay_stems = [_stem(t) for t in hay_tokens]
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
        key = normalize_text(term)
        if key in seen:
            continue
        if _term_matches(term, haystack, hay_tokens):
            seen.add(key)
            matched.append(term)
    return matched


def _row_role_rules(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or _load_dictionary()
    return payload.get("row_role_rules") or {}


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
            if _match_terms(rules.get("overhead_markers") or [], haystack, hay_tokens):
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
        if _match_terms(rules.get(marker_key) or [], role_haystack, role_hay_tokens):
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
    weights = (payload.get("scoring") or {}).get("weights") or {}
    thresholds = (payload.get("scoring") or {}).get("decision_thresholds") or {}
    min_delta = int(thresholds.get("min_delta_between_top_two", 3))
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
        preferred_sections: set[str] = set()
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
            section_scores[section_id] = section_scores.get(section_id, 0) + int(
                weights.get("conflict_prefer_boost", 4)
            )
            section_matches.setdefault(section_id, {}).setdefault(
                "conflict_prefer_terms", []
            ).extend(terms)
            preferred_sections.add(section_id)
            applied.append(f"{rule_id}:prefer:{section_id}")
        for penalty in rule.get("penalize") or []:
            section_id = str(penalty.get("section_id") or "")
            if section_id not in sections_by_id:
                continue
            terms = _match_terms(penalty.get("when_any") or [], haystack, hay_tokens)
            if not terms:
                continue
            section_scores[section_id] = section_scores.get(section_id, 0) + int(
                weights.get("conflict_penalty", -4)
            )
            section_matches.setdefault(section_id, {}).setdefault(
                "conflict_penalty_terms", []
            ).extend(terms)
            applied.append(f"{rule_id}:penalize:{section_id}")
        if len(preferred_sections) == 1:
            section_id = next(iter(preferred_sections))
            other_max = max(
                (
                    score
                    for other_id, score in section_scores.items()
                    if other_id != section_id
                ),
                default=0,
            )
            if section_scores.get(section_id, 0) <= other_max:
                section_scores[section_id] = other_max + min_delta
                section_matches.setdefault(section_id, {}).setdefault(
                    "conflict_override_rules", []
                ).append(rule_id)
                applied.append(f"{rule_id}:override:{section_id}")
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
        if normalize_text(term) == haystack:
            score += int(weights.get("exact_strong_phrase", 7)) * 2
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
) -> tuple[int, dict[str, list[str]]]:
    best_score = 0
    best_matches: dict[str, list[str]] = {}
    for subtype in section.get("subtypes") or []:
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
) -> tuple[list[ClassificationCandidate], dict[str, list[str]]]:
    scored: list[tuple[dict[str, Any], int, dict[str, list[str]]]] = []
    for subtype in section.get("subtypes") or []:
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


def classify_work(
    name: str,
    section: str | None = None,
    *,
    row_role: str | None = None,
) -> ClassificationResult:
    payload = _load_dictionary()
    weights = (payload.get("scoring") or {}).get("weights") or {}
    thresholds = (payload.get("scoring") or {}).get("decision_thresholds") or {}
    text = " ".join(part for part in (name, section) if part)
    haystack = normalize_text(text)
    hay_tokens = haystack.split()
    version = dictionary_version(payload)
    resolved_role = row_role or classify_row_role(name, section, payload=payload)
    sections = payload.get("sections") or []
    sections_by_id = {str(section["id"]): section for section in sections}

    if not haystack:
        return ClassificationResult(
            section_code=None,
            section_name=None,
            subtype_code=UNKNOWN_SUBTYPE_CODE,
            subtype_name=UNKNOWN_SUBTYPE_NAME,
            score=0,
            confidence="low",
            needs_review=True,
            source="rule_based",
            matched_terms={},
            candidates=[],
            related_sections=[],
            reason="empty_name",
            dictionary_version=version,
            row_role=resolved_role,
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
        )

    section_scores: dict[str, int] = {}
    section_matches: dict[str, dict[str, list[str]]] = {}
    for sec in sections:
        score, matched = _score_section(sec, haystack, hay_tokens, weights)
        subtype_hint_score, subtype_hint_matches = _best_subtype_hint(
            sec, haystack, hay_tokens, weights
        )
        if subtype_hint_score > 0:
            score += subtype_hint_score
            matched["subtype_hint_terms"] = [
                term
                for values in subtype_hint_matches.values()
                for term in values
            ]
        section_id = str(sec["id"])
        section_scores[section_id] = score
        section_matches[section_id] = matched

    profile_rules = _apply_estimate_profiles(
        section_scores, section_matches, haystack, hay_tokens, payload
    )
    conflict_rules = _apply_conflict_rules(
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
            source="rule_based",
            matched_terms={},
            candidates=[],
            related_sections=[],
            reason="no_section_match",
            dictionary_version=version,
            row_role=resolved_role,
        )

    section_candidates = _section_candidates(ranked_sections, sections_by_id, thresholds)
    winner_id, winner_score, winner_matches = ranked_sections[0]
    second_score = ranked_sections[1][1] if len(ranked_sections) > 1 else 0
    section_delta = winner_score - second_score
    auto_min = int(thresholds.get("auto_accept_min_score", 9))
    min_delta = int(thresholds.get("min_delta_between_top_two", 3))
    review_min = int(thresholds.get("review_min_score", 5))
    section_needs_review = winner_score < auto_min or section_delta < min_delta
    source = "rule_based" if not section_needs_review else "rule_based_review"

    winning_section = sections_by_id[winner_id]
    subtype_candidates, subtype_matches = _subtype_candidates(
        winning_section, winner_score, haystack, hay_tokens, weights, thresholds, payload
    )
    best_subtype = subtype_candidates[0] if subtype_candidates else None

    subtype_needs_review = best_subtype is None or best_subtype.needs_review
    needs_review = section_needs_review or subtype_needs_review or winner_score < review_min
    matched_terms: dict[str, list[str]] = {
        **winner_matches,
        **(subtype_matches or {}),
    }
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
        subtype_score = best_subtype.subtype_score or 0
        total_score = best_subtype.score
        subtype_delta = best_subtype.delta_to_next or 0
        reason = "auto_accept" if not needs_review else "needs_review"
    else:
        subtype_code = UNKNOWN_SUBTYPE_CODE
        subtype_name = UNKNOWN_SUBTYPE_NAME
        subtype_score = 0
        total_score = winner_score
        subtype_delta = 0
        reason = "subtype_ambiguous"

    confidence = _confidence(total_score, min(section_delta, subtype_delta), needs_review, thresholds)
    candidates = section_candidates + subtype_candidates
    return ClassificationResult(
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
