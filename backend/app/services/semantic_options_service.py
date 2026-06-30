"""Semantic stage-option resolution and safe operation projection generation.

The module implements the v6.5.0 contracts without depending on preview, DB or
worker infrastructure.  It mutates stage-instance dictionaries in place so the
same payload can later be persisted by the import pipeline.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

STAGE_OPTION_SOURCE_VALUES = frozenset(
    {
        "manual_override",
        "project_structure_options",
        "classified_from_row",
        "auto_single_allowed_option",
    }
)

PROJECTION_GENERATION_STATUS_VALUES = frozenset(
    {
        "pending",
        "generated",
        "skipped_no_selected_options",
        "skipped_recommendations_not_confirmed",
        "skipped_not_applicable",
        "blocked",
        "failed",
    }
)

STRICT_STAGE_OPTION_CONTRACT_VERSION = "1.1"

MATERIALIZATION_SOURCES = frozenset(
    {
        "matched_to_source_row",
        "explicitly_confirmed",
        "manually_added",
        "quantity_inherited_under_versioned_rules",
    }
)


@dataclass(frozen=True)
class SemanticOptionIssue:
    code: str
    canonical_stage_id: str
    stage_instance_id: str | None = None
    details: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "canonical_stage_id": self.canonical_stage_id,
        }
        if self.stage_instance_id is not None:
            payload["stage_instance_id"] = self.stage_instance_id
        if self.details is not None:
            payload["details"] = deepcopy(dict(self.details))
        return payload


class StageOptionValidationError(ValueError):
    """Structured validation failure shared by preview and import."""

    def __init__(self, issues: Sequence[SemanticOptionIssue]):
        ordered = tuple(issues)
        self.issues = ordered
        self.code = ordered[0].code if ordered else "invalid_stage_option"
        super().__init__(self.code)

    def as_details(self) -> dict[str, Any]:
        details: dict[str, Any] = {"issues": [issue.as_dict() for issue in self.issues]}
        if len(self.issues) == 1:
            issue = self.issues[0]
            details["canonical_stage_id"] = issue.canonical_stage_id
            details.update(dict(issue.details or {}))
        missing = [
            {
                "canonical_stage_id": issue.canonical_stage_id,
                **dict(issue.details or {}),
            }
            for issue in self.issues
            if issue.code == "stage_option_required"
        ]
        if missing:
            details["missing"] = missing
        return details


@dataclass(frozen=True)
class StageOptionValidationResult:
    normalized_options: dict[str, str]
    dropped_stage_options: tuple[dict[str, Any], ...]
    auto_selected_options: tuple[dict[str, Any], ...]


def _condition_matches(condition: Any, building_params: Mapping[str, Any]) -> bool:
    if not isinstance(condition, Mapping):
        return True
    parameter = str(condition.get("parameter") or "").strip()
    if not parameter:
        return True
    actual = building_params.get(parameter)
    if "equals" in condition:
        return actual == condition.get("equals")
    if "in" in condition and isinstance(condition.get("in"), Sequence):
        return actual in condition.get("in")
    return True


def _stage_is_applicable(
    stage: Mapping[str, Any],
    *,
    stage_instances: Sequence[Mapping[str, Any]],
    building_params: Mapping[str, Any],
) -> bool:
    stage_id = str(stage.get("canonical_stage_id") or "")
    template_number = str(stage.get("number") or stage.get("template_stage_number") or "")
    has_instance = any(
        str(instance.get("canonical_stage_id") or "") == stage_id
        and (
            not template_number
            or str(instance.get("template_stage_number") or instance.get("number") or "") == template_number
        )
        for instance in stage_instances
    )
    condition = stage.get("applicable_when")
    if condition is None and isinstance(stage.get("stage_options_policy"), Mapping):
        condition = stage["stage_options_policy"].get("applicable_when")
    return has_instance and _condition_matches(condition, building_params)


def _applicable_option_ids(
    stage: Mapping[str, Any], building_params: Mapping[str, Any]
) -> list[str]:
    result: list[str] = []
    for option in stage.get("stage_options") or []:
        if not isinstance(option, Mapping):
            continue
        option_id = str(option.get("id") or "").strip()
        if option_id and _condition_matches(option.get("applicable_when"), building_params):
            result.append(option_id)
    return result


def validate_required_stage_options(
    *,
    variant: Mapping[str, Any],
    stage_instances: Sequence[Mapping[str, Any]],
    building_params: Mapping[str, Any],
    submitted_project_structure_options: Mapping[str, Any],
    inherited_draft_options: Mapping[str, Any] | None = None,
) -> StageOptionValidationResult:
    """Validate and normalize the strict building-level selectable-one contract."""
    if not isinstance(submitted_project_structure_options, Mapping):
        raise StageOptionValidationError((SemanticOptionIssue(
            "invalid_stage_option", "", details={"expected_type": "object"}
        ),))
    inherited = inherited_draft_options or {}
    if not isinstance(inherited, Mapping):
        inherited = {}

    selectable = [
        stage for stage in (variant.get("stages") or [])
        if isinstance(stage, Mapping)
        and str(_selection_policy(stage).get("mode") or stage.get("stage_options_mode") or "none") == "selectable_one"
    ]
    selectable.sort(key=lambda stage: str(stage.get("number") or ""))
    known_stage_ids = {str(stage.get("canonical_stage_id") or "") for stage in selectable}
    merged: dict[str, Any] = {str(key): value for key, value in inherited.items()}
    merged.update({str(key): value for key, value in submitted_project_structure_options.items()})

    issues: list[SemanticOptionIssue] = []
    normalized: dict[str, str] = {}
    dropped: list[dict[str, Any]] = []
    auto_selected: list[dict[str, Any]] = []

    for stage_id in sorted(set(merged) - known_stage_ids):
        issues.append(SemanticOptionIssue(
            "invalid_stage_option", stage_id, details={"reason": "stage_has_no_selectable_options"}
        ))

    for stage in selectable:
        stage_id = str(stage.get("canonical_stage_id") or "")
        policy = _selection_policy(stage)
        applicable = _stage_is_applicable(
            stage, stage_instances=stage_instances, building_params=building_params
        )
        explicitly_submitted = stage_id in submitted_project_structure_options
        inherited_value_present = stage_id in inherited
        value_present = stage_id in merged
        raw_value = merged.get(stage_id)

        if not applicable:
            if explicitly_submitted:
                issues.append(SemanticOptionIssue(
                    "stage_option_not_applicable",
                    stage_id,
                    details={
                        "option_id": raw_value,
                        "reason": "basement_disabled" if not building_params.get("has_basement") else "stage_not_applicable",
                    },
                ))
            elif inherited_value_present:
                dropped.append({
                    "canonical_stage_id": stage_id,
                    "option_id": inherited.get(stage_id),
                    "reason": "stage_not_applicable",
                })
            continue

        allowed = _applicable_option_ids(stage, building_params)
        if value_present:
            if isinstance(raw_value, (list, tuple)):
                issues.append(SemanticOptionIssue(
                    "too_many_stage_options_selected",
                    stage_id,
                    details={"selected_count": len(raw_value), "max_selected": 1},
                ))
                continue
            option_id = _trim_option(raw_value)
            if option_id is None or option_id not in allowed:
                issues.append(SemanticOptionIssue(
                    "invalid_stage_option",
                    stage_id,
                    details={"option_id": raw_value, "allowed_option_ids": allowed},
                ))
                continue
            normalized[stage_id] = option_id
            continue

        required = bool(policy.get("selection_required", False)) or int(policy.get("min_selected", 0)) > 0
        if len(allowed) == 1:
            normalized[stage_id] = allowed[0]
            auto_selected.append({
                "canonical_stage_id": stage_id,
                "option_id": allowed[0],
                "source": "auto_single_allowed_option",
            })
        elif required:
            issues.append(SemanticOptionIssue(
                "stage_option_required",
                stage_id,
                details={
                    "template_stage_number": str(stage.get("number") or ""),
                    "allowed_option_ids": allowed,
                },
            ))

    if issues:
        priority = {
            "too_many_stage_options_selected": 0,
            "invalid_stage_option": 1,
            "stage_option_not_applicable": 2,
            "stage_option_required": 3,
        }
        issues.sort(key=lambda issue: (priority.get(issue.code, 9), issue.canonical_stage_id))
        raise StageOptionValidationError(tuple(issues))
    return StageOptionValidationResult(normalized, tuple(dropped), tuple(auto_selected))


def build_stage_option_requirements(
    *,
    variant: Mapping[str, Any],
    stage_instances: Sequence[Mapping[str, Any]],
    building_params: Mapping[str, Any],
    normalized_options: Mapping[str, str],
    auto_selected_stage_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    auto_ids = set(auto_selected_stage_ids)
    result: list[dict[str, Any]] = []
    for stage in variant.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        policy = _selection_policy(stage)
        if str(policy.get("mode") or stage.get("stage_options_mode") or "none") != "selectable_one":
            continue
        if not _stage_is_applicable(stage, stage_instances=stage_instances, building_params=building_params):
            continue
        stage_id = str(stage.get("canonical_stage_id") or "")
        selected = normalized_options.get(stage_id)
        options = [
            {"id": str(option.get("id")), "title": str(option.get("title") or option.get("id"))}
            for option in stage.get("stage_options") or []
            if isinstance(option, Mapping)
            and str(option.get("id") or "") in _applicable_option_ids(stage, building_params)
        ]
        result.append({
            "canonical_stage_id": stage_id,
            "template_stage_number": str(stage.get("number") or ""),
            "title": str(stage.get("title") or ""),
            "selection_mode": "one_of",
            "required": bool(policy.get("selection_required", False)) or int(policy.get("min_selected", 0)) > 0,
            "selected_option_id": selected,
            "selection_source": (
                "auto_single_allowed_option" if stage_id in auto_ids else "project_structure_options"
            ) if selected else None,
            "options": options,
        })
    return result


@dataclass(frozen=True)
class SemanticOptionResolutionReport:
    normalized_project_structure_options: Mapping[str, Any]
    issues: tuple[SemanticOptionIssue, ...]
    trace: tuple[Mapping[str, Any], ...]
    resolved_stage_instances: int
    needs_review_stage_instances: int

    @property
    def valid(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalized_project_structure_options": deepcopy(
                dict(self.normalized_project_structure_options)
            ),
            "issues": [item.as_dict() for item in self.issues],
            "trace": [deepcopy(dict(item)) for item in self.trace],
            "resolved_stage_instances": self.resolved_stage_instances,
            "needs_review_stage_instances": self.needs_review_stage_instances,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class OperationProjectionReport:
    generated_stage_instances: int = 0
    skipped_no_selected_options: int = 0
    skipped_recommendations_not_confirmed: int = 0
    blocked_stage_instances: int = 0
    failed_stage_instances: int = 0
    generated_projections: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "generated_stage_instances": self.generated_stage_instances,
            "skipped_no_selected_options": self.skipped_no_selected_options,
            "skipped_recommendations_not_confirmed": self.skipped_recommendations_not_confirmed,
            "blocked_stage_instances": self.blocked_stage_instances,
            "failed_stage_instances": self.failed_stage_instances,
            "generated_projections": self.generated_projections,
        }


def _stage_index(variant: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(stage.get("canonical_stage_id") or ""): stage
        for stage in (variant.get("stages") or [])
        if isinstance(stage, dict) and stage.get("canonical_stage_id")
    }


def _stage_option_index(stage: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(option.get("id") or ""): option
        for option in (stage.get("stage_options") or [])
        if isinstance(option, dict) and option.get("id")
    }


def _selection_policy(stage: Mapping[str, Any]) -> dict[str, Any]:
    policy = stage.get("stage_options_policy")
    if isinstance(policy, dict):
        return dict(policy)
    mode = str(stage.get("stage_options_mode") or "none")
    return {
        "mode": mode,
        "selection_required": mode == "selectable_one",
        "min_selected": 1 if mode == "selectable_one" else 0,
        "max_selected": 1 if mode == "selectable_one" else len(stage.get("stage_options") or []),
        "selection_scope": str(stage.get("selection_scope") or "building"),
    }


def _trim_option(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _normalize_sequence(value: Any) -> tuple[list[str], int, bool]:
    """Return normalized values, submitted count and whether the type is valid."""
    if not isinstance(value, list):
        return [], 0, False
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in value:
        option_id = _trim_option(raw)
        if option_id is None:
            # Non-string and empty entries are invalid option values.  Preserve a
            # sentinel that will fail the allowed-options check deterministically.
            option_id = ""
        if option_id not in seen:
            seen.add(option_id)
            normalized.append(option_id)
    return normalized, len(value), True


def _lookup_source_value(
    source: Mapping[str, Any] | None,
    *,
    stage_instance_id: str,
    canonical_stage_id: str,
) -> tuple[bool, Any]:
    if not isinstance(source, Mapping):
        return False, None
    if stage_instance_id in source:
        return True, source[stage_instance_id]
    if canonical_stage_id in source:
        return True, source[canonical_stage_id]
    return False, None


def _issue_reason_for_required(stage: Mapping[str, Any]) -> str:
    validation = stage.get("selection_validation")
    if isinstance(validation, dict) and validation.get("structural_group_reason_code"):
        return str(validation["structural_group_reason_code"])
    return "stage_option_required"


def _validate_branch_groups(
    *,
    variant: Mapping[str, Any],
    stage: Mapping[str, Any],
    selected: Sequence[str],
) -> str | None:
    policy = _selection_policy(stage)
    configured_ids = [str(value) for value in (policy.get("branch_group_ids") or []) if value]
    if not configured_ids:
        return None
    group_by_id = {
        str(group.get("id") or ""): group
        for group in (variant.get("branch_groups") or [])
        if isinstance(group, dict) and group.get("id")
    }
    selected_set = set(selected)
    for group_id in configured_ids:
        group = group_by_id.get(group_id)
        if not group:
            continue
        option_ids = {str(value) for value in (group.get("option_ids") or [])}
        count = len(selected_set & option_ids)
        minimum = int(group.get("min_selected", 1))
        maximum = int(group.get("max_selected", 1))
        if count < minimum or count > maximum:
            return str(group.get("reason_code") or _issue_reason_for_required(stage))
    return None


def _normalize_value(
    *,
    variant: Mapping[str, Any],
    stage: Mapping[str, Any],
    raw_value: Any,
    source_name: str,
    canonical_stage_id: str,
    stage_instance_id: str,
    trace: list[Mapping[str, Any]],
) -> tuple[list[str], SemanticOptionIssue | None]:
    policy = _selection_policy(stage)
    mode = str(policy.get("mode") or stage.get("stage_options_mode") or "none")
    allowed = list(_stage_option_index(stage))
    allowed_set = set(allowed)

    if mode == "selectable_one":
        option_id = _trim_option(raw_value)
        if option_id is None or isinstance(raw_value, (list, tuple, dict)):
            return [], SemanticOptionIssue(
                "invalid_stage_option", canonical_stage_id, stage_instance_id,
                {"source": source_name, "submitted_value": deepcopy(raw_value)},
            )
        selected = [option_id]
    elif mode == "selectable_many":
        selected, submitted_count, type_valid = _normalize_sequence(raw_value)
        if not type_valid:
            return [], SemanticOptionIssue(
                "invalid_stage_option", canonical_stage_id, stage_instance_id,
                {"source": source_name, "expected_type": "array[string]"},
            )
        if submitted_count != len(selected):
            trace.append(
                {
                    "event": "duplicate_stage_options_removed",
                    "canonical_stage_id": canonical_stage_id,
                    "stage_instance_id": stage_instance_id,
                    "submitted_count": submitted_count,
                    "normalized_count": len(selected),
                }
            )
    else:
        return [], None

    unknown = [value for value in selected if value not in allowed_set]
    if unknown:
        return [], SemanticOptionIssue(
            "invalid_stage_option", canonical_stage_id, stage_instance_id,
            {"source": source_name, "unknown_options": unknown, "allowed_options": allowed},
        )

    minimum = int(policy.get("min_selected", 0))
    maximum = int(policy.get("max_selected", len(allowed)))
    if len(selected) < minimum:
        return [], SemanticOptionIssue(
            _issue_reason_for_required(stage), canonical_stage_id, stage_instance_id,
            {"selected_count": len(selected), "min_selected": minimum},
        )
    if len(selected) > maximum:
        return [], SemanticOptionIssue(
            "too_many_stage_options_selected", canonical_stage_id, stage_instance_id,
            {"selected_count": len(selected), "max_selected": maximum},
        )

    branch_error = _validate_branch_groups(variant=variant, stage=stage, selected=selected)
    if branch_error:
        return [], SemanticOptionIssue(
            branch_error, canonical_stage_id, stage_instance_id,
            {"selected_options": list(selected)},
        )
    return selected, None


def normalize_project_structure_options(
    variant: Mapping[str, Any],
    project_structure_options: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], tuple[SemanticOptionIssue, ...], tuple[Mapping[str, Any], ...]]:
    """Normalize persisted building-level options without resolving instances."""
    source = project_structure_options or {}
    if not isinstance(source, Mapping):
        issue = SemanticOptionIssue(
            "invalid_stage_option", "", None, {"expected_type": "object"}
        )
        return {}, (issue,), ()

    stage_by_id = _stage_index(variant)
    normalized: dict[str, Any] = {}
    issues: list[SemanticOptionIssue] = []
    trace: list[Mapping[str, Any]] = []
    for canonical_stage_id, raw_value in source.items():
        canonical_stage_id = str(canonical_stage_id).strip()
        stage = stage_by_id.get(canonical_stage_id)
        if stage is None or str(stage.get("stage_options_mode") or "none") not in {
            "selectable_one", "selectable_many"
        }:
            issues.append(
                SemanticOptionIssue(
                    "invalid_stage_option", canonical_stage_id, None,
                    {"reason": "stage_has_no_selectable_options"},
                )
            )
            continue
        selected, issue = _normalize_value(
            variant=variant,
            stage=stage,
            raw_value=raw_value,
            source_name="project_structure_options",
            canonical_stage_id=canonical_stage_id,
            stage_instance_id="",
            trace=trace,
        )
        if issue:
            issues.append(issue)
            continue
        mode = str(_selection_policy(stage).get("mode"))
        if mode == "selectable_one" and selected:
            normalized[canonical_stage_id] = selected[0]
        elif mode == "selectable_many" and selected:
            # Empty arrays are deliberately not persisted.
            normalized[canonical_stage_id] = selected
    return normalized, tuple(issues), tuple(trace)


def resolve_semantic_options(
    variant: Mapping[str, Any],
    stage_instances: list[MutableMapping[str, Any]],
    *,
    project_structure_options: Mapping[str, Any] | None = None,
    manual_overrides: Mapping[str, Any] | None = None,
    classified_options: Mapping[str, Any] | None = None,
) -> SemanticOptionResolutionReport:
    """Resolve options for all stage instances according to v6.5 priority."""
    normalized_project, normalization_issues, normalization_trace = (
        normalize_project_structure_options(variant, project_structure_options)
    )
    issues: list[SemanticOptionIssue] = list(normalization_issues)
    normalization_issue_by_stage = {
        issue.canonical_stage_id: issue
        for issue in normalization_issues
        if issue.canonical_stage_id
    }
    trace: list[Mapping[str, Any]] = list(normalization_trace)
    stage_by_id = _stage_index(variant)
    resolved_count = 0
    review_count = 0
    strict_contract = str(variant.get("stage_option_selection_contract_version") or "") == STRICT_STAGE_OPTION_CONTRACT_VERSION

    for instance in stage_instances:
        canonical_stage_id = str(instance.get("canonical_stage_id") or "")
        stage_instance_id = str(instance.get("stage_instance_id") or "")
        stage = stage_by_id.get(canonical_stage_id)
        if stage is None:
            continue
        policy = _selection_policy(stage)
        mode = str(policy.get("mode") or stage.get("stage_options_mode") or "none")
        if mode not in {"selectable_one", "selectable_many"}:
            continue

        instance["semantic_stage_option_ids"] = []
        instance["semantic_stage_option_id"] = None
        instance["semantic_stage_option_title"] = None
        instance["execution_applicability"] = "applicable"
        instance["stage_option_source"] = None
        instance["stage_option_auto_selected"] = False
        instance["classification_status"] = "resolved"
        instance["reason_code"] = None
        instance["operation_resolution_status"] = "pending"
        instance["resolved_operation_codes"] = []
        instance["recommendation_only"] = True
        instance["projection_generation_status"] = "pending"
        instance["projection_generation_reason_code"] = None
        instance["projection_generation_failure_code"] = None
        instance["projection_generation_failure_details"] = None

        selected: list[str] = []
        selected_source: str | None = None
        source_found = False
        raw_value: Any = None

        sources = (
            (("project_structure_options", normalized_project),)
            if strict_contract
            else (
                ("manual_override", manual_overrides),
                ("project_structure_options", normalized_project),
                ("classified_from_row", classified_options),
            )
        )
        for source_name, source in sources:
            found, candidate = _lookup_source_value(
                source,
                stage_instance_id=stage_instance_id,
                canonical_stage_id=canonical_stage_id,
            )
            if found:
                source_found = True
                raw_value = candidate
                selected_source = source_name
                break

        if source_found:
            selected, issue = _normalize_value(
                variant=variant,
                stage=stage,
                raw_value=raw_value,
                source_name=str(selected_source),
                canonical_stage_id=canonical_stage_id,
                stage_instance_id=stage_instance_id,
                trace=trace,
            )
            if issue:
                issues.append(issue)
                instance["classification_status"] = "needs_review"
                instance["reason_code"] = issue.code
                instance["projection_generation_status"] = "blocked"
                instance["projection_generation_reason_code"] = issue.code
                review_count += 1
                continue
        else:
            project_issue = normalization_issue_by_stage.get(canonical_stage_id)
            if project_issue is not None and isinstance(project_structure_options, Mapping) and canonical_stage_id in project_structure_options:
                instance["classification_status"] = "needs_review"
                instance["reason_code"] = project_issue.code
                instance["projection_generation_status"] = "blocked"
                instance["projection_generation_reason_code"] = project_issue.code
                review_count += 1
                continue
            allowed = _applicable_option_ids(stage, {})
            if len(allowed) == 1:
                selected = [allowed[0]]
                selected_source = "auto_single_allowed_option"
                instance["stage_option_auto_selected"] = True
                trace.append(
                    {
                        "event": "stage_option_auto_selected",
                        "canonical_stage_id": canonical_stage_id,
                        "stage_instance_id": stage_instance_id,
                        "selected_option": allowed[0],
                        "reason": "single_allowed_option_after_context_filter",
                    }
                )
            else:
                minimum = int(policy.get("min_selected", 0))
                required = bool(policy.get("selection_required", False)) or minimum > 0
                if required:
                    reason = _issue_reason_for_required(stage)
                    issue = SemanticOptionIssue(
                        reason, canonical_stage_id, stage_instance_id,
                        {"allowed_options": allowed},
                    )
                    issues.append(issue)
                    instance["classification_status"] = "needs_review"
                    instance["reason_code"] = reason
                    instance["projection_generation_status"] = "blocked"
                    instance["projection_generation_reason_code"] = reason
                    review_count += 1
                    continue
                selected = []
                selected_source = None

        instance["semantic_stage_option_ids"] = list(selected)
        instance["semantic_stage_option_id"] = selected[0] if len(selected) == 1 else None
        if len(selected) == 1:
            option = _stage_option_index(stage).get(selected[0]) or {}
            instance["semantic_stage_option_title"] = option.get("title")
            instance["execution_applicability"] = str(
                option.get("execution_applicability") or "applicable"
            )
        if selected_source:
            if selected_source not in STAGE_OPTION_SOURCE_VALUES:
                raise ValueError(f"Unsupported stage_option_source: {selected_source}")
            instance["stage_option_source"] = selected_source
        instance["stage_option_auto_selected"] = selected_source == "auto_single_allowed_option"
        instance["classification_status"] = "resolved"
        instance["reason_code"] = None
        instance["operation_resolution_status"] = "resolved"
        if instance["execution_applicability"] == "not_applicable":
            instance["projection_generation_status"] = "skipped_not_applicable"
            instance["resolved_operation_codes"] = []
        resolved_count += 1

        if selected_source == "project_structure_options" and str(policy.get("selection_scope") or "building") == "building":
            trace.append(
                {
                    "event": "building_stage_options_copied_to_instance",
                    "canonical_stage_id": canonical_stage_id,
                    "stage_instance_id": stage_instance_id,
                    "floor_number": instance.get("floor_number"),
                    "selected_options": list(selected),
                    "stage_option_source": "project_structure_options",
                }
            )

    return SemanticOptionResolutionReport(
        normalized_project_structure_options=normalized_project,
        issues=tuple(issues),
        trace=tuple(trace),
        resolved_stage_instances=resolved_count,
        needs_review_stage_instances=review_count,
    )


def _recommended_candidates(
    stage_instance: Mapping[str, Any],
    stage: Mapping[str, Any],
) -> list[dict[str, Any]]:
    options = _stage_option_index(stage)
    result: list[dict[str, Any]] = []
    for option_id in stage_instance.get("semantic_stage_option_ids") or []:
        option = options.get(str(option_id))
        if option is None:
            continue
        for operation_code in option.get("operation_codes") or []:
            result.append(
                {
                    "stage_instance_id": stage_instance.get("stage_instance_id"),
                    "canonical_stage_id": stage_instance.get("canonical_stage_id"),
                    "semantic_stage_option_id": option_id,
                    "operation_code": str(operation_code),
                    "operation_package_code": None,
                    "recommendation_status": option.get("recommendation_status", "recommended"),
                    "recommendation_source": option.get(
                        "recommendation_source", "construction_work_autofill_dictionary"
                    ),
                    "requires_source_match_or_confirmation": bool(
                        option.get("requires_source_match_or_confirmation", True)
                    ),
                }
            )
        for package_code in option.get("package_codes") or []:
            result.append(
                {
                    "stage_instance_id": stage_instance.get("stage_instance_id"),
                    "canonical_stage_id": stage_instance.get("canonical_stage_id"),
                    "semantic_stage_option_id": option_id,
                    "operation_code": None,
                    "operation_package_code": str(package_code),
                    "recommendation_status": option.get("recommendation_status", "recommended"),
                    "recommendation_source": option.get(
                        "recommendation_source", "construction_work_autofill_dictionary"
                    ),
                    "requires_source_match_or_confirmation": bool(
                        option.get("requires_source_match_or_confirmation", True)
                    ),
                }
            )
    return result


def _evidence_identity(evidence: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        evidence.get("source_row_key"),
        evidence.get("stage_instance_id"),
        evidence.get("semantic_stage_option_id"),
        evidence.get("operation_code"),
        evidence.get("operation_package_code"),
        evidence.get("work_scope_key"),
        evidence.get("applicability_hash"),
        evidence.get("applicability_hash_version"),
    )


def _materialize_stage_projections(
    *,
    stage_instance: MutableMapping[str, Any],
    stage: Mapping[str, Any],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected = {str(value) for value in (stage_instance.get("semantic_stage_option_ids") or [])}
    candidates = _recommended_candidates(stage_instance, stage)
    candidate_keys = {
        (
            str(candidate.get("semantic_stage_option_id") or ""),
            str(candidate.get("operation_code") or ""),
            str(candidate.get("operation_package_code") or ""),
        )
        for candidate in candidates
    }
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for evidence in evidence_rows:
        source = str(evidence.get("materialization_source") or "")
        if source not in MATERIALIZATION_SOURCES:
            continue
        option_id = str(evidence.get("semantic_stage_option_id") or "")
        if option_id not in selected:
            continue
        operation_code = str(evidence.get("operation_code") or "")
        package_code = str(evidence.get("operation_package_code") or "")
        if (option_id, operation_code, package_code) not in candidate_keys:
            # Manual/source-only operations may be present in the stage but not
            # in the recommended option composition.  Permit them only when the
            # source is explicit and the stage operation registry contains them.
            stage_operations = {
                str(item.get("operation_code") or "")
                for item in (stage.get("operations") or [])
                if isinstance(item, dict)
            }
            stage_packages = {str(value) for value in (stage.get("operation_packages") or [])}
            explicit_source = source in {"matched_to_source_row", "explicitly_confirmed", "manually_added"}
            if not explicit_source or not (
                (operation_code and operation_code in stage_operations)
                or (package_code and package_code in stage_packages)
            ):
                continue
        identity = _evidence_identity(evidence)
        if identity in seen:
            continue
        seen.add(identity)
        projection_id = evidence.get("projection_id")
        if not projection_id:
            encoded_identity = json.dumps(
                list(identity), ensure_ascii=False, separators=(",", ":"), default=str
            ).encode("utf-8")
            projection_id = "sp:" + hashlib.sha256(encoded_identity).hexdigest()[:28]
        projection = {
            "projection_id": projection_id,
            "source_row_key": evidence.get("source_row_key"),
            "stage_instance_id": stage_instance.get("stage_instance_id"),
            "template_stage_number": stage_instance.get("template_stage_number"),
            "stage_number": stage_instance.get("number"),
            "floor_number": stage_instance.get("floor_number"),
            "floor_kind": stage_instance.get("floor_kind"),
            "floor_label": stage_instance.get("floor_label"),
            "floor_component": stage_instance.get("floor_component"),
            "component_role": stage_instance.get("component_role"),
            "operation_code": operation_code or None,
            "operation_package_code": package_code or None,
            "semantic_stage_option_id": option_id,
            "stage_option_source": stage_instance.get("stage_option_source"),
            "work_scope_key": evidence.get("work_scope_key"),
            "applicability_hash": evidence.get("applicability_hash"),
            "applicability_hash_version": evidence.get("applicability_hash_version"),
            "applicability_schema_version": evidence.get("applicability_schema_version"),
            "quantity": evidence.get("quantity"),
            "unit_code": evidence.get("unit_code"),
            "quantity_source": evidence.get("quantity_source"),
            "materialization_source": source,
        }
        # This service intentionally never derives calculation outputs.
        projection.pop("labor", None)
        projection.pop("labor_hours", None)
        projection.pop("duration", None)
        result.append(projection)
    return result


def generate_semantic_operation_projections(
    variant: Mapping[str, Any],
    stage_instances: list[MutableMapping[str, Any]],
    *,
    evidence: Iterable[Mapping[str, Any]] = (),
) -> OperationProjectionReport:
    """Generate only confirmed/matched/manual/inherited operation projections.

    Recommended candidates are retained for UI/audit but are never materialized
    into quantity/labor/duration merely because they exist in taxonomy.
    """
    stage_by_id = _stage_index(variant)
    evidence_by_instance: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        evidence_by_instance.setdefault(str(item.get("stage_instance_id") or ""), []).append(item)

    counts = {
        "generated_stage_instances": 0,
        "skipped_no_selected_options": 0,
        "skipped_recommendations_not_confirmed": 0,
        "blocked_stage_instances": 0,
        "failed_stage_instances": 0,
        "generated_projections": 0,
    }

    for instance in stage_instances:
        canonical_stage_id = str(instance.get("canonical_stage_id") or "")
        stage = stage_by_id.get(canonical_stage_id)
        if stage is None:
            continue
        mode = str(_selection_policy(stage).get("mode") or stage.get("stage_options_mode") or "none")
        if mode not in {"selectable_one", "selectable_many"}:
            continue

        instance["projection_generation_reason_code"] = None
        instance["projection_generation_failure_code"] = None
        instance["projection_generation_failure_details"] = None
        instance["operation_projections"] = []
        candidates = _recommended_candidates(instance, stage)
        instance["recommended_operation_candidates"] = candidates
        selected = list(instance.get("semantic_stage_option_ids") or [])

        if instance.get("execution_applicability") == "not_applicable":
            instance["projection_generation_status"] = "skipped_not_applicable"
            instance["recommendation_only"] = False
            instance["resolved_operation_codes"] = []
            instance["recommended_operation_candidates"] = []
            continue

        if instance.get("classification_status") == "needs_review" or instance.get("reason_code"):
            reason = str(instance.get("reason_code") or "stage_option_required")
            instance["projection_generation_status"] = "blocked"
            instance["projection_generation_reason_code"] = reason
            instance["recommendation_only"] = True
            counts["blocked_stage_instances"] += 1
            continue

        if not selected:
            instance["projection_generation_status"] = "skipped_no_selected_options"
            instance["recommendation_only"] = True
            instance["resolved_operation_codes"] = []
            counts["skipped_no_selected_options"] += 1
            continue

        try:
            projections = _materialize_stage_projections(
                stage_instance=instance,
                stage=stage,
                evidence_rows=evidence_by_instance.get(str(instance.get("stage_instance_id") or ""), []),
            )
        except Exception as exc:  # noqa: BLE001 - persisted technical failure contract
            instance["projection_generation_status"] = "failed"
            instance["projection_generation_failure_code"] = "semantic_projection_generation_failed"
            instance["projection_generation_failure_details"] = {
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
            instance["recommendation_only"] = True
            counts["failed_stage_instances"] += 1
            continue

        instance["operation_projections"] = projections
        if projections:
            instance["projection_generation_status"] = "generated"
            instance["recommendation_only"] = False
            instance["resolved_operation_codes"] = sorted(
                {
                    str(item.get("operation_code"))
                    for item in projections
                    if item.get("operation_code")
                }
            )
            counts["generated_stage_instances"] += 1
            counts["generated_projections"] += len(projections)
        else:
            instance["projection_generation_status"] = "skipped_recommendations_not_confirmed"
            instance["recommendation_only"] = True
            instance["resolved_operation_codes"] = []
            counts["skipped_recommendations_not_confirmed"] += 1

    return OperationProjectionReport(**counts)


def validate_projection_generation_state(stage_instance: Mapping[str, Any]) -> tuple[str, ...]:
    """Framework-neutral equivalent of stage-2 DB CHECK constraints."""
    errors: list[str] = []
    status = stage_instance.get("projection_generation_status")
    reason = stage_instance.get("projection_generation_reason_code")
    failure = stage_instance.get("projection_generation_failure_code")
    details = stage_instance.get("projection_generation_failure_details")
    if status not in PROJECTION_GENERATION_STATUS_VALUES:
        return ("invalid_projection_generation_status",)
    if status == "blocked":
        if not reason:
            errors.append("blocked_projection_generation_reason_required")
        if failure is not None or details is not None:
            errors.append("blocked_projection_generation_failure_fields_forbidden")
    elif status == "failed":
        if reason is not None:
            errors.append("failed_projection_generation_reason_forbidden")
        if not failure:
            errors.append("failed_projection_generation_failure_code_required")
    elif status == "skipped_not_applicable":
        if reason is not None or failure is not None or details is not None:
            errors.append("not_applicable_projection_generation_error_fields_forbidden")
        if stage_instance.get("operation_projections"):
            errors.append("not_applicable_projection_generation_operations_forbidden")
    elif reason is not None or failure is not None or details is not None:
        errors.append("projection_generation_auxiliary_fields_forbidden")
    return tuple(errors)
