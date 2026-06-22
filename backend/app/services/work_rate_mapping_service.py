"""Automatic and manual mapping of work-rate items to canonical taxonomy."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.services.work_rate_import_service import normalize_name
from app.services.work_rate_models import (
    MAPPING_CONTEXTUAL,
    MAPPING_DIRECT,
    MAPPING_EXCLUDED,
    MAPPING_OBSERVATION,
    MAPPING_PACKAGE,
    MAPPING_STATUS_EXCLUDED,
    MAPPING_STATUS_MAPPED,
    MAPPING_STATUS_OBSERVATION,
    MAPPING_STATUS_PARTIAL,
    MAPPING_STATUS_UNMAPPED,
    MAPPING_UNMAPPED,
    REVIEW_AUTO,
    REVIEW_NEEDED,
    REVIEW_NEW,
    WorkRateItem,
    WorkRateMapping,
)


@dataclass(slots=True)
class MappingResult:
    item: WorkRateItem
    mappings: list[WorkRateMapping] = field(default_factory=list)
    operation_code: str | None = None
    object_candidates: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.as_dict(),
            "mappings": [mapping.as_dict() for mapping in self.mappings],
            "operation_code": self.operation_code,
            "object_candidates": self.object_candidates,
            "diagnostics": self.diagnostics,
        }


def adapt_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Read both legacy and future rule field names without modifying JSON."""
    return {
        "operation_code": rule.get("operation_code") or rule.get("operation"),
        "object_scope_code": rule.get("object_scope_code") or rule.get("object"),
        "section_id": rule.get("section_id"),
        "subtype_id": rule.get("subtype_id"),
        "preferred_stage_number": rule.get("preferred_stage_number"),
    }


def _term_match(term: str, haystack: str) -> bool:
    normalized = normalize_name(term)
    if not normalized:
        return False
    if len(normalized) <= 3:
        return bool(re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", haystack))
    return normalized in haystack


class WorkRateMappingService:
    def __init__(self, taxonomy: str | Path | dict[str, Any]):
        if isinstance(taxonomy, dict):
            self.payload = taxonomy
        else:
            with open(taxonomy, encoding="utf-8") as fh:
                self.payload = json.load(fh)
        self.policy = self.payload.get("operation_object_resolution_policy") or {}
        self.operations: dict[str, list[str]] = {
            str(code): [str(term) for term in terms]
            for code, terms in (self.policy.get("operations") or {}).items()
            if isinstance(terms, list)
        }
        self.operation_metadata: dict[str, dict[str, Any]] = {
            str(code): dict(meta)
            for code, meta in (self.policy.get("operation_metadata") or {}).items()
            if isinstance(meta, dict)
        }
        self.operation_packages: dict[str, dict[str, Any]] = {
            str(code): dict(meta)
            for code, meta in (self.policy.get("operation_packages") or {}).items()
            if isinstance(meta, dict)
        }
        self.objects: dict[str, dict[str, Any]] = {
            str(code): dict(value)
            for code, value in (self.policy.get("objects") or {}).items()
            if isinstance(value, dict)
        }
        self.rules = [adapt_rule(rule) for rule in (self.policy.get("rules") or []) if isinstance(rule, dict)]
        self.taxonomy_version = str(
            self.payload.get("dictionary_version")
            or (self.payload.get("meta") or {}).get("dictionary_version")
            or ""
        )
        self.policy_version = str(self.policy.get("version") or "")
        self.subtypes: dict[str, dict[str, Any]] = {}
        for section in self.payload.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_id = str(section.get("id") or "")
            for subtype in section.get("subtypes") or []:
                if not isinstance(subtype, dict):
                    continue
                code = f"{section_id}/{subtype.get('id')}"
                self.subtypes[code] = {
                    "section_id": section_id,
                    "subtype_id": str(subtype.get("id") or ""),
                    "title": str(subtype.get("title") or ""),
                    "payload": subtype,
                }

    def validate_taxonomy_code(self, code: str | None) -> bool:
        return bool(code and code in self.subtypes)

    def detect_operation(self, item: WorkRateItem) -> tuple[str | None, float, list[str]]:
        haystack = normalize_name(" ".join(filter(None, [item.name, item.notes])))
        matches: list[tuple[int, int, str, list[str]]] = []
        for operation_code, terms in self.operations.items():
            matched = [term for term in terms if _term_match(term, haystack)]
            if matched:
                longest = max(len(normalize_name(term)) for term in matched)
                matches.append((longest, len(matched), operation_code, matched))
        if not matches:
            return None, 0.0, []
        matches.sort(reverse=True)
        longest, count, code, matched = matches[0]
        exact = any(normalize_name(term) == haystack for term in matched)
        confidence = 0.99 if exact else min(0.98, 0.86 + min(longest, 60) / 500 + count * 0.02)
        return code, round(confidence, 4), matched

    def detect_objects(self, item: WorkRateItem) -> list[tuple[str, float, list[str]]]:
        haystack = normalize_name(" ".join(filter(None, [item.name, item.notes])))
        found: list[tuple[str, float, list[str]]] = []
        for object_code, definition in self.objects.items():
            terms: list[str] = []
            for key in ("title_terms", "description_terms", "terms"):
                value = definition.get(key)
                if isinstance(value, list):
                    terms.extend(str(term) for term in value)
            matched = [term for term in terms if _term_match(term, haystack)]
            if matched:
                confidence = min(0.98, 0.82 + max(len(normalize_name(term)) for term in matched) / 300)
                found.append((object_code, round(confidence, 4), matched))
        found.sort(key=lambda row: row[1], reverse=True)
        return found

    def _rules_for_operation(self, operation_code: str) -> list[dict[str, Any]]:
        return [rule for rule in self.rules if rule.get("operation_code") == operation_code]

    def _mapping_from_rule(
        self,
        item: WorkRateItem,
        rule: dict[str, Any],
        *,
        mapping_mode: str,
        confidence: float,
        source: str,
        is_primary: bool,
        diagnostics: dict[str, Any] | None = None,
    ) -> WorkRateMapping:
        section_id = str(rule.get("section_id") or "") or None
        subtype_id = str(rule.get("subtype_id") or "") or None
        taxonomy_code = f"{section_id}/{subtype_id}" if section_id and subtype_id else None
        package = self.operation_packages.get(str(rule.get("operation_code") or "")) or {}
        return WorkRateMapping(
            rate_item_id=item.id,
            operation_code=rule.get("operation_code"),
            taxonomy_section_id=section_id,
            taxonomy_subtype_id=subtype_id,
            taxonomy_code=taxonomy_code,
            object_scope_code=rule.get("object_scope_code"),
            mapping_mode=mapping_mode,
            confidence=round(confidence, 4),
            mapping_source=source,
            taxonomy_version=self.taxonomy_version,
            operation_policy_version=self.policy_version,
            is_primary=is_primary,
            included_operations=list(package.get("included_operations") or []),
            diagnostics={
                "preferred_stage_number": rule.get("preferred_stage_number"),
                **(diagnostics or {}),
            },
        )

    def _fallback_subtype_candidates(self, item: WorkRateItem) -> list[tuple[float, str]]:
        haystack = normalize_name(" ".join(filter(None, [item.name, item.notes])))
        tokens = set(haystack.split())
        candidates: list[tuple[float, str]] = []
        for code, definition in self.subtypes.items():
            title = normalize_name(definition["title"])
            title_tokens = set(title.split())
            overlap = tokens & title_tokens
            if not overlap:
                continue
            score = len(overlap) / max(1, len(title_tokens))
            if title and title in haystack:
                score += 0.45
            if score >= 0.45:
                candidates.append((min(0.89, score), code))
        candidates.sort(reverse=True)
        return candidates[:5]

    def map_item(self, item: WorkRateItem) -> MappingResult:
        if item.row_role != "work":
            mapping = WorkRateMapping(
                rate_item_id=item.id,
                mapping_mode=MAPPING_EXCLUDED,
                confidence=1.0,
                mapping_source="row_role",
                taxonomy_version=self.taxonomy_version,
                operation_policy_version=self.policy_version,
                diagnostics={"row_role": item.row_role},
            )
            item.mapping_status = MAPPING_STATUS_EXCLUDED
            item.has_active_mapping = True
            item.auto_applicable = False
            if item.review_status == REVIEW_NEW:
                item.review_status = REVIEW_AUTO
            return MappingResult(item=item, mappings=[mapping], diagnostics={"reason": "non_work_row"})

        is_observation = item.mapping_status == MAPPING_STATUS_OBSERVATION
        operation_code, operation_confidence, matched_terms = self.detect_operation(item)
        object_rows = self.detect_objects(item)
        object_codes = [row[0] for row in object_rows]
        diagnostics: dict[str, Any] = {
            "operation_matched_terms": matched_terms,
            "operation_confidence": operation_confidence,
            "object_candidates": [
                {"code": code, "confidence": confidence, "matched_terms": terms}
                for code, confidence, terms in object_rows
            ],
        }

        if not operation_code:
            fallback = self._fallback_subtype_candidates(item)
            mappings: list[WorkRateMapping] = []
            for index, (score, code) in enumerate(fallback):
                section_id, subtype_id = code.split("/", 1)
                mappings.append(
                    WorkRateMapping(
                        rate_item_id=item.id,
                        taxonomy_section_id=section_id,
                        taxonomy_subtype_id=subtype_id,
                        taxonomy_code=code,
                        mapping_mode=MAPPING_OBSERVATION if is_observation else MAPPING_UNMAPPED,
                        confidence=round(score, 4),
                        mapping_source="market_observation" if is_observation else "taxonomy_title_fallback",
                        taxonomy_version=self.taxonomy_version,
                        operation_policy_version=self.policy_version,
                        is_primary=index == 0,
                    )
                )
            item.mapping_status = MAPPING_STATUS_OBSERVATION if is_observation else MAPPING_STATUS_UNMAPPED
            item.review_status = REVIEW_NEEDED
            item.review_reason = item.review_reason or (
                "observation_operation_not_detected" if is_observation else "operation_not_detected"
            )
            item.auto_applicable = False
            return MappingResult(item=item, mappings=mappings, diagnostics=diagnostics)

        metadata = self.operation_metadata.get(operation_code) or {}
        unit_hints = {str(value) for value in (metadata.get("unit_hints") or [])}
        unit_valid = not unit_hints or item.unit_code in unit_hints
        diagnostics["unit_hints"] = sorted(unit_hints)
        diagnostics["unit_compatible"] = unit_valid
        if not unit_valid:
            item.review_status = REVIEW_NEEDED
            item.review_reason = "operation_unit_conflict"
            item.auto_applicable = False

        all_rules = self._rules_for_operation(operation_code)
        object_rule_candidates: list[tuple[dict[str, Any], float]] = []
        if object_rows:
            confidence_by_object = {code: conf for code, conf, _ in object_rows}
            for rule in all_rules:
                obj = rule.get("object_scope_code")
                if obj in confidence_by_object:
                    combined = min(0.99, operation_confidence * 0.60 + confidence_by_object[obj] * 0.40 + 0.03)
                    object_rule_candidates.append((rule, combined))

        chosen_rules: list[tuple[dict[str, Any], float]]
        if object_rule_candidates:
            chosen_rules = object_rule_candidates
        elif len(all_rules) == 1:
            # One policy target means the operation itself is sufficient for a
            # direct candidate; unit compatibility still gates auto-accept.
            chosen_rules = [(all_rules[0], operation_confidence)]
        else:
            chosen_rules = [(rule, operation_confidence * 0.88) for rule in all_rules]

        kind = str(metadata.get("kind") or "atomic")
        package_definition = self.operation_packages.get(operation_code)
        is_package = kind == "package" or package_definition is not None
        item.is_package_candidate = is_package

        if not chosen_rules:
            item.mapping_status = MAPPING_STATUS_OBSERVATION if is_observation else MAPPING_STATUS_UNMAPPED
            item.review_status = REVIEW_NEEDED
            item.review_reason = item.review_reason or (
                "observation_has_no_taxonomy_rule" if is_observation else "operation_has_no_taxonomy_rule"
            )
            item.auto_applicable = False
            return MappingResult(
                item=item,
                mappings=[
                    WorkRateMapping(
                        rate_item_id=item.id,
                        operation_code=operation_code,
                        mapping_mode=(
                            MAPPING_OBSERVATION
                            if is_observation
                            else (MAPPING_PACKAGE if is_package else MAPPING_UNMAPPED)
                        ),
                        confidence=operation_confidence,
                        mapping_source="market_observation" if is_observation else "operation_only",
                        taxonomy_version=self.taxonomy_version,
                        operation_policy_version=self.policy_version,
                        included_operations=list((package_definition or {}).get("included_operations") or []),
                    )
                ],
                operation_code=operation_code,
                object_candidates=object_codes,
                diagnostics=diagnostics,
            )

        # Deduplicate identical taxonomy/object targets.
        dedup: dict[tuple[str | None, str | None], tuple[dict[str, Any], float]] = {}
        for rule, score in chosen_rules:
            key = (
                f"{rule.get('section_id')}/{rule.get('subtype_id')}",
                rule.get("object_scope_code"),
            )
            current = dedup.get(key)
            if current is None or score > current[1]:
                dedup[key] = (rule, score)
        ranked = sorted(dedup.values(), key=lambda row: row[1], reverse=True)

        if is_package:
            mapping_mode = MAPPING_PACKAGE
        elif len(ranked) == 1:
            mapping_mode = MAPPING_DIRECT
        else:
            mapping_mode = MAPPING_CONTEXTUAL

        mappings = [
            self._mapping_from_rule(
                item,
                rule,
                mapping_mode=mapping_mode,
                confidence=score,
                source="operation_object_policy",
                is_primary=index == 0,
                diagnostics={"operation_confidence": operation_confidence},
            )
            for index, (rule, score) in enumerate(ranked)
        ]

        top = mappings[0].confidence if mappings else 0.0
        second = mappings[1].confidence if len(mappings) > 1 else 0.0
        delta = top - second
        auto_accept = (
            bool(mappings)
            and top >= 0.90
            and (len(mappings) == 1 or delta >= 0.15)
            and unit_valid
            and mapping_mode != MAPPING_CONTEXTUAL
        )

        observation = is_observation or item.source_payload.get("source_kind") == "market_estimate_observation"

        if observation:
            for mapping in mappings:
                mapping.mapping_mode = MAPPING_OBSERVATION
                mapping.mapping_source = "market_observation"
            item.mapping_status = MAPPING_STATUS_OBSERVATION
            item.review_status = REVIEW_NEEDED
            item.review_reason = item.review_reason or "observation_requires_manual_approval"
            item.auto_applicable = False
        elif auto_accept:
            item.mapping_status = MAPPING_STATUS_MAPPED
            item.has_active_mapping = True
            item.review_status = REVIEW_AUTO if item.review_status == REVIEW_NEW else item.review_status
            item.auto_applicable = True
        else:
            item.mapping_status = MAPPING_STATUS_PARTIAL if mappings else MAPPING_STATUS_UNMAPPED
            item.review_status = REVIEW_NEEDED
            item.review_reason = item.review_reason or (
                "contextual_mapping_requires_object" if mapping_mode == MAPPING_CONTEXTUAL else "mapping_confidence_below_threshold"
            )
            item.auto_applicable = False

        diagnostics.update({"top_score": top, "delta": delta, "auto_accept": auto_accept})
        return MappingResult(
            item=item,
            mappings=mappings,
            operation_code=operation_code,
            object_candidates=object_codes,
            diagnostics=diagnostics,
        )

    def auto_map(self, items: Iterable[WorkRateItem]) -> list[MappingResult]:
        return [self.map_item(item) for item in items]

    def approve_mapping(
        self,
        item: WorkRateItem,
        mapping: WorkRateMapping,
        *,
        approved_by: str | None = None,
    ) -> None:
        from app.services.work_rate_models import utcnow_iso

        if mapping.mapping_mode == MAPPING_OBSERVATION:
            item.approved_as_rate = True
        mapping.mapping_source = "manual"
        mapping.approved_by = approved_by
        mapping.approved_at = utcnow_iso()
        mapping.is_active = True
        item.mapping_status = MAPPING_STATUS_MAPPED
        item.has_active_mapping = True
        item.review_status = "approved"
        item.review_reason = None
        item.auto_applicable = True
