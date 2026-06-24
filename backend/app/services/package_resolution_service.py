"""Projection-aware package/atomic conflict resolution.

The resolver works after stage and quantity projection enrichment.  It never
clones or deletes financial Estimate rows.  Resolution is attached to
``raw_data`` and individual ``ktp_quantity_projections`` so the same source row
may be enabled on one floor and suppressed/reviewed on another.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

PACKAGE_RESOLUTION_VERSION = "brick-house-package-resolution-v1"


@dataclass(frozen=True)
class PackageResolutionReport:
    source_rows: int = 0
    calculation_units: int = 0
    package_only_groups: int = 0
    atomic_only_groups: int = 0
    auto_atomic_groups: int = 0
    manual_package_groups: int = 0
    manual_atomic_groups: int = 0
    unresolved_groups: int = 0
    suppressed_units: int = 0
    review_units: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "resolution_version": PACKAGE_RESOLUTION_VERSION,
            "source_rows": self.source_rows,
            "calculation_units": self.calculation_units,
            "package_only_groups": self.package_only_groups,
            "atomic_only_groups": self.atomic_only_groups,
            "auto_atomic_groups": self.auto_atomic_groups,
            "manual_package_groups": self.manual_package_groups,
            "manual_atomic_groups": self.manual_atomic_groups,
            "unresolved_groups": self.unresolved_groups,
            "suppressed_units": self.suppressed_units,
            "review_units": self.review_units,
        }


@dataclass
class _Unit:
    row_index: int
    row: Any
    raw: dict[str, Any]
    projection: dict[str, Any]
    operation_code: str
    package_code: str | None
    candidate_package_code: str | None
    candidate_package_codes: set[str]
    stage_instance_id: str
    template_stage_number: str
    semantic_stage_option_id: str | None
    work_scope_key: str | None
    work_scope_resolved: bool
    group_key: str | None = None

    @property
    def kind(self) -> str:
        return "package" if self.package_code else "atomic"


def _stable_hash(payload: Any, length: int = 32) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _explicit_scope(raw: dict[str, Any], projection: dict[str, Any]) -> tuple[str | None, bool]:
    """Return a scope safe enough for automatic duplicate resolution.

    ``auto:...`` values generated for quantity inheritance deliberately are not
    considered explicit package scopes.  They include operation wording and can
    make a package and its children appear unrelated.
    """
    for key in ("source_scope_id", "parent_work_id", "section_block_id"):
        value = _clean(raw.get(key))
        if value:
            return value, True
    value = _clean(projection.get("work_scope_key") or raw.get("work_scope_key"))
    if value and not value.startswith("auto:"):
        return value, True
    return None, False


def _stage_package_index(variant: dict[str, Any]) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    stage_packages: dict[str, set[str]] = {}
    option_packages: dict[tuple[str, str], set[str]] = {}
    for stage in variant.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        stage_number = str(stage.get("number") or "")
        if not stage_number:
            continue
        stage_packages[stage_number] = {
            str(code) for code in (stage.get("operation_packages") or []) if code
        }
        for option in stage.get("stage_options") or []:
            if not isinstance(option, dict):
                continue
            option_id = _clean(option.get("id") or option.get("semantic_id"))
            if option_id:
                option_packages[(stage_number, option_id)] = {
                    str(code) for code in (option.get("package_codes") or []) if code
                }
    return stage_packages, option_packages


def _reverse_package_index(packages: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for package_code, package in packages.items():
        if not isinstance(package, dict):
            continue
        for operation_code in package.get("included_operations") or []:
            code = _clean(operation_code)
            if code:
                result.setdefault(code, set()).add(str(package_code))
    return result


def _projection_list(row: Any, raw: dict[str, Any]) -> list[dict[str, Any]]:
    items = [
        item for item in (raw.get("ktp_quantity_projections") or []) if isinstance(item, dict)
    ]
    if items:
        return items
    # Backward-compatible calculation unit for rows not processed by stage 6.
    return [{
        "projection_id": None,
        "target_stage_instance_id": raw.get("stage_instance_id"),
        "target_template_stage_number": raw.get("template_stage_number"),
        "semantic_stage_option_id": raw.get("semantic_stage_option_id") or raw.get("stage_option_id"),
        "work_scope_key": raw.get("work_scope_key"),
        "quantity": getattr(row, "quantity", None),
        "quantity_source": "estimate",
        "_synthetic_projection": True,
    }]


def _candidate_packages_for_atomic(
    operation_code: str,
    *,
    template_stage_number: str,
    semantic_stage_option_id: str | None,
    reverse_index: dict[str, set[str]],
    stage_packages: dict[str, set[str]],
    option_packages: dict[tuple[str, str], set[str]],
) -> set[str]:
    candidates = set(reverse_index.get(operation_code) or set())
    allowed = set(stage_packages.get(template_stage_number) or set())
    option_allowed = set(option_packages.get((template_stage_number, semantic_stage_option_id or "")) or set())
    if option_allowed:
        allowed = option_allowed
    if allowed:
        candidates &= allowed
    return candidates


def _manual_mode(units: Iterable[_Unit]) -> tuple[str | None, bool]:
    values: set[str] = set()
    for unit in units:
        value = _clean(
            unit.projection.get("package_resolution_mode")
            or unit.raw.get("package_resolution_mode")
        )
        if value in {"package_only", "atomic_only"}:
            values.add(value)
    if len(values) == 1:
        return next(iter(values)), False
    if len(values) > 1:
        return None, True
    return None, False


def _set_unit_state(
    unit: _Unit,
    *,
    mode: str,
    enabled: bool,
    suppressed: bool,
    conflict: bool,
    needs_review: bool,
    reason: str,
    diagnostics: dict[str, Any],
) -> None:
    target = unit.projection
    target.update({
        "package_resolution_version": PACKAGE_RESOLUTION_VERSION,
        "package_resolution_group_key": unit.group_key,
        "package_resolution_mode": mode,
        "package_resolution_reason": reason,
        "package_conflict": bool(conflict),
        "calculation_enabled": bool(enabled),
        "calculation_suppressed": bool(suppressed),
        "package_resolution_needs_review": bool(needs_review),
        "package_conflict_diagnostics": diagnostics,
    })
    if needs_review:
        target["needs_review"] = True
        target["review_reason"] = reason


def _mark_membership_ambiguous(unit: _Unit, candidates: set[str]) -> None:
    reason = "package_membership_ambiguous"
    diagnostics = {
        "operation_code": unit.operation_code,
        "candidate_package_codes": sorted(candidates),
        "stage_instance_id": unit.stage_instance_id,
        "template_stage_number": unit.template_stage_number,
    }
    _set_unit_state(
        unit,
        mode="manual_required",
        enabled=False,
        suppressed=False,
        conflict=True,
        needs_review=True,
        reason=reason,
        diagnostics=diagnostics,
    )


def resolve_package_atomic_conflicts(
    rows: list[Any],
    *,
    variant: dict[str, Any],
) -> PackageResolutionReport:
    """Resolve package/atomic calculation representation per stage instance.

    Automatic resolution is intentionally conservative:
    * package only -> package calculation;
    * atomic only -> atomic calculation;
    * package + complete explicit atomic coverage -> atomic calculation;
    * package + partial atomic coverage -> review;
    * package + atomic without an explicit work scope -> review;
    * manual ``package_only`` / ``atomic_only`` overrides are respected.
    """
    registry = variant.get("operation_registry") or {}
    packages = registry.get("operation_packages") or {}
    if not isinstance(packages, dict):
        packages = {}
    reverse_index = _reverse_package_index(packages)
    stage_packages, option_packages = _stage_package_index(variant)

    units: list[_Unit] = []
    membership_review_units: list[_Unit] = []

    for row_index, row in enumerate(rows):
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        row.raw_data = raw
        raw.pop("package_resolution_groups", None)
        raw["package_resolution_version"] = PACKAGE_RESOLUTION_VERSION
        raw["package_conflict"] = False
        raw["package_resolution_needs_review"] = False
        raw["calculation_suppressed"] = False

        if raw.get("row_role") != "work" or not raw.get("work_type_applicable", True):
            continue
        operation_code = _clean(raw.get("operation_code"))
        package_code = _clean(raw.get("operation_package_code"))
        if operation_code in packages:
            package_code = package_code or operation_code
        if not operation_code:
            continue

        projections = _projection_list(row, raw)
        for projection in projections:
            stage_instance_id = _clean(
                projection.get("target_stage_instance_id") or raw.get("stage_instance_id")
            )
            template_stage_number = _clean(
                projection.get("target_template_stage_number") or raw.get("template_stage_number")
            )
            option_id = _clean(
                projection.get("semantic_stage_option_id")
                or raw.get("semantic_stage_option_id")
                or raw.get("stage_option_id")
            )
            if not stage_instance_id or not template_stage_number:
                continue
            scope_key, scope_resolved = _explicit_scope(raw, projection)
            unit = _Unit(
                row_index=row_index,
                row=row,
                raw=raw,
                projection=projection,
                operation_code=operation_code,
                package_code=package_code,
                candidate_package_code=package_code,
                candidate_package_codes={package_code} if package_code else set(),
                stage_instance_id=stage_instance_id,
                template_stage_number=template_stage_number,
                semantic_stage_option_id=option_id,
                work_scope_key=scope_key,
                work_scope_resolved=scope_resolved,
            )
            if not package_code:
                candidates = _candidate_packages_for_atomic(
                    operation_code,
                    template_stage_number=template_stage_number,
                    semantic_stage_option_id=option_id,
                    reverse_index=reverse_index,
                    stage_packages=stage_packages,
                    option_packages=option_packages,
                )
                unit.candidate_package_codes = set(candidates)
                unit.candidate_package_code = next(iter(candidates), None) if len(candidates) == 1 else None
            units.append(unit)

    # Resolve an atomic operation that belongs to several package definitions
    # only against package rows actually present in the same stage/scope.  An
    # atomic-only row remains valid even if it can theoretically participate in
    # several packages.
    present_packages: dict[tuple[str, str | None, str], set[str]] = {}
    for unit in units:
        if not unit.package_code:
            continue
        context_key = (
            unit.stage_instance_id,
            unit.work_scope_key if unit.work_scope_resolved else None,
            unit.semantic_stage_option_id or "",
        )
        present_packages.setdefault(context_key, set()).add(unit.package_code)

    resolved_units: list[_Unit] = []
    for unit in units:
        if unit.package_code or len(unit.candidate_package_codes) <= 1:
            resolved_units.append(unit)
            continue
        context_key = (
            unit.stage_instance_id,
            unit.work_scope_key if unit.work_scope_resolved else None,
            unit.semantic_stage_option_id or "",
        )
        matching = unit.candidate_package_codes & present_packages.get(context_key, set())
        if len(matching) == 1:
            unit.candidate_package_code = next(iter(matching))
            resolved_units.append(unit)
        elif len(matching) > 1:
            membership_review_units.append(unit)
            _mark_membership_ambiguous(unit, matching)
        else:
            # No package row in this context: calculate the atomic row normally.
            unit.candidate_package_code = None
            resolved_units.append(unit)
    units = resolved_units

    groups: dict[tuple[str, str, str | None, str], list[_Unit]] = {}
    for unit in units:
        package_code = unit.candidate_package_code
        if not package_code:
            # Atomic operation not included in a package is independently valid.
            _set_unit_state(
                unit,
                mode="atomic_only",
                enabled=True,
                suppressed=False,
                conflict=False,
                needs_review=False,
                reason="atomic_not_in_package",
                diagnostics={"operation_code": unit.operation_code},
            )
            continue
        option_marker = unit.semantic_stage_option_id or ""
        key = (
            unit.stage_instance_id,
            package_code,
            unit.work_scope_key if unit.work_scope_resolved else None,
            option_marker,
        )
        unit.group_key = "pkg:" + _stable_hash([*key], 28)
        groups.setdefault(key, []).append(unit)

    counters = {
        "package_only_groups": 0,
        "atomic_only_groups": 0,
        "auto_atomic_groups": 0,
        "manual_package_groups": 0,
        "manual_atomic_groups": 0,
        "unresolved_groups": 0,
    }

    for (_stage_instance, package_code, explicit_scope, _option), group in groups.items():
        package = packages.get(package_code) or {}
        package_units = [unit for unit in group if unit.package_code == package_code]
        atomic_units = [unit for unit in group if not unit.package_code]
        included = {str(code) for code in (package.get("included_operations") or []) if code}
        present_atomic = {unit.operation_code for unit in atomic_units}
        manual_mode, override_conflict = _manual_mode(group)
        scope_resolved = explicit_scope is not None
        diagnostics = {
            "package_code": package_code,
            "stage_instance_id": group[0].stage_instance_id,
            "work_scope_key": explicit_scope,
            "scope_resolved": scope_resolved,
            "included_operation_codes": sorted(included),
            "present_atomic_operation_codes": sorted(present_atomic),
            "missing_atomic_operation_codes": sorted(included - present_atomic),
            "package_row_indexes": sorted({u.row_index for u in package_units}),
            "atomic_row_indexes": sorted({u.row_index for u in atomic_units}),
            "allow_mixed_calculation": bool(package.get("allow_mixed_calculation", False)),
            "prefer": package.get("prefer") or "explicit_atomic",
        }

        if package_units and not atomic_units:
            counters["package_only_groups"] += 1
            for unit in package_units:
                _set_unit_state(unit, mode="package_only", enabled=True, suppressed=False,
                                conflict=False, needs_review=False,
                                reason="package_without_atomic_rows", diagnostics=diagnostics)
            continue
        if atomic_units and not package_units:
            counters["atomic_only_groups"] += 1
            for unit in atomic_units:
                _set_unit_state(unit, mode="atomic_only", enabled=True, suppressed=False,
                                conflict=False, needs_review=False,
                                reason="atomic_rows_without_package", diagnostics=diagnostics)
            continue

        if override_conflict:
            counters["unresolved_groups"] += 1
            reason = "package_resolution_override_conflict"
            for unit in group:
                _set_unit_state(unit, mode="manual_required", enabled=False, suppressed=False,
                                conflict=True, needs_review=True, reason=reason, diagnostics=diagnostics)
            continue

        if manual_mode == "package_only":
            counters["manual_package_groups"] += 1
            for unit in package_units:
                _set_unit_state(unit, mode="package_only", enabled=True, suppressed=False,
                                conflict=False, needs_review=False,
                                reason="manual_package_only", diagnostics=diagnostics)
            for unit in atomic_units:
                _set_unit_state(unit, mode="package_only", enabled=False, suppressed=True,
                                conflict=False, needs_review=False,
                                reason="suppressed_by_manual_package_only", diagnostics=diagnostics)
            continue

        if manual_mode == "atomic_only":
            counters["manual_atomic_groups"] += 1
            for unit in package_units:
                _set_unit_state(unit, mode="atomic_only", enabled=False, suppressed=True,
                                conflict=False, needs_review=False,
                                reason="suppressed_by_manual_atomic_only", diagnostics=diagnostics)
            for unit in atomic_units:
                _set_unit_state(unit, mode="atomic_only", enabled=True, suppressed=False,
                                conflict=False, needs_review=False,
                                reason="manual_atomic_only", diagnostics=diagnostics)
            continue

        if not scope_resolved:
            counters["unresolved_groups"] += 1
            reason = "package_scope_ambiguous"
            for unit in group:
                _set_unit_state(unit, mode="manual_required", enabled=False, suppressed=False,
                                conflict=True, needs_review=True, reason=reason, diagnostics=diagnostics)
            continue

        if package.get("allow_mixed_calculation"):
            for unit in group:
                _set_unit_state(unit, mode="mixed_allowed", enabled=True, suppressed=False,
                                conflict=False, needs_review=False,
                                reason="package_policy_allows_mixed", diagnostics=diagnostics)
            continue

        package_has_quantity = any(
            unit.projection.get("quantity") not in (None, "") for unit in package_units
        )
        full_atomic_coverage = bool(included) and included.issubset(present_atomic)
        if full_atomic_coverage or not package_has_quantity:
            counters["auto_atomic_groups"] += 1
            reason = "explicit_atomic_full_coverage" if full_atomic_coverage else "package_row_without_quantity"
            for unit in package_units:
                _set_unit_state(unit, mode="atomic_only", enabled=False, suppressed=True,
                                conflict=False, needs_review=False, reason=reason, diagnostics=diagnostics)
            for unit in atomic_units:
                _set_unit_state(unit, mode="atomic_only", enabled=True, suppressed=False,
                                conflict=False, needs_review=False, reason=reason, diagnostics=diagnostics)
            continue

        counters["unresolved_groups"] += 1
        reason = "package_atomic_partial_conflict"
        for unit in group:
            _set_unit_state(unit, mode="manual_required", enabled=False, suppressed=False,
                            conflict=True, needs_review=True, reason=reason, diagnostics=diagnostics)

    # Aggregate projection-level decisions onto source rows for preview/Gantt.
    suppressed_units = review_units = 0
    for row in rows:
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        decisions = [
            item for item in (raw.get("ktp_quantity_projections") or [])
            if isinstance(item, dict) and item.get("package_resolution_version")
        ]
        # Synthetic fallback units are not stored in the projection list.  Pull
        # their state from matching _Unit objects instead.
        if not decisions:
            decisions = [
                unit.projection for unit in units
                if unit.row is row and unit.projection.get("package_resolution_version")
            ]
        groups_payload: dict[str, dict[str, Any]] = {}
        for decision in decisions:
            group_key = _clean(decision.get("package_resolution_group_key")) or "independent"
            groups_payload[group_key] = {
                "group_key": decision.get("package_resolution_group_key"),
                "mode": decision.get("package_resolution_mode"),
                "reason": decision.get("package_resolution_reason"),
                "conflict": bool(decision.get("package_conflict")),
                "needs_review": bool(decision.get("package_resolution_needs_review")),
                "diagnostics": decision.get("package_conflict_diagnostics") or {},
            }
            suppressed_units += bool(decision.get("calculation_suppressed"))
            review_units += bool(decision.get("package_resolution_needs_review"))
        raw["package_resolution_groups"] = list(groups_payload.values())
        raw["package_conflict"] = any(item["conflict"] for item in groups_payload.values())
        raw["package_resolution_needs_review"] = any(item["needs_review"] for item in groups_payload.values())
        modes = {str(item["mode"]) for item in groups_payload.values() if item.get("mode")}
        raw["package_resolution_mode"] = next(iter(modes)) if len(modes) == 1 else ("per_projection" if modes else None)
        raw["calculation_suppressed"] = bool(decisions) and all(
            bool(item.get("calculation_suppressed")) for item in decisions
        )
        if raw["package_resolution_needs_review"]:
            reasons = [str(item["reason"]) for item in groups_payload.values() if item.get("needs_review")]
            raw["operator_review_required"] = True
            raw["operator_review_reason"] = reasons[0] if reasons else "package_conflict_unresolved"
            raw["rate_needs_review"] = True
            raw["rate_review_reason"] = reasons[0] if reasons else "package_conflict_unresolved"

    report = PackageResolutionReport(
        source_rows=len(rows),
        calculation_units=len(units) + len(membership_review_units),
        package_only_groups=counters["package_only_groups"],
        atomic_only_groups=counters["atomic_only_groups"],
        auto_atomic_groups=counters["auto_atomic_groups"],
        manual_package_groups=counters["manual_package_groups"],
        manual_atomic_groups=counters["manual_atomic_groups"],
        unresolved_groups=counters["unresolved_groups"] + len(membership_review_units),
        suppressed_units=int(suppressed_units),
        review_units=int(review_units) + len(membership_review_units),
    )
    for row in rows:
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        raw["package_resolution_report"] = report.as_dict()
    return report
