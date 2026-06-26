"""Deterministic KTP/GPR helpers for dynamic-floor project variants.

The module is framework-neutral.  It turns quantity-projection metadata into
stage-instance WBS groups, calculates catalog-grounded labour for every
projection and builds deterministic finish-to-start dependencies for brick
house variant 2.7.  Other variants keep the existing AI dependency resolver.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

BRICK_HOUSE_VARIANT_ID = "residential_construction_kirpichnye_doma"
BRICK_HOUSE_STAGE_PREFIX = "2.7."
STRUCTURAL_COMPLETION_STAGE_INSTANCE_ID = (
    f"{BRICK_HOUSE_VARIANT_ID}:structural_completion"
)

STAGE_LEVEL_METADATA_FIELDS: tuple[str, ...] = (
    "stage_instance_id",
    "template_stage_number",
    "stage_number",
    "floor_number",
    "floor_kind",
    "floor_label",
    "floor_component",
    "component_role",
)

ROW_LEVEL_METADATA_FIELDS: tuple[str, ...] = (
    "source_row_key",
    "projection_id",
    *STAGE_LEVEL_METADATA_FIELDS,
    "operation_code",
    "operation_package_code",
    "semantic_stage_option_id",
    "stage_option_source",
    "work_scope_key",
    "applicability_hash",
    "applicability_hash_version",
    "applicability_schema_version",
)


@dataclass(frozen=True)
class ProjectionGroupDescriptor:
    key: str
    title: str
    sort_order: float
    stage_instance_id: str | None
    template_stage_number: str | None
    stage_number: str | None
    canonical_stage_id: str | None
    floor_number: int | None
    floor_kind: str | None
    floor_label: str | None
    floor_component: str | None
    component_role: str | None


@dataclass(frozen=True)
class StructuralCompletionMilestone:
    stage_instance_id: str
    task_kind: str
    duration: int
    wait_group_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage_instance_id": self.stage_instance_id,
            "task_kind": self.task_kind,
            "duration": self.duration,
            "wait_group_ids": list(self.wait_group_ids),
        }


@dataclass(frozen=True)
class FloorDependencyReport:
    applicable: bool
    edges: tuple[tuple[str, str], ...]
    unresolved_group_ids: tuple[str, ...] = ()
    milestone: StructuralCompletionMilestone | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "applicable": self.applicable,
            "edges": [
                {"group_id": group_id, "depends_on_group_id": depends_on}
                for group_id, depends_on in self.edges
            ],
            "unresolved_group_ids": list(self.unresolved_group_ids),
            "milestone": self.milestone.as_dict() if self.milestone else None,
        }


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _text(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def projection_group_descriptor(
    raw_group: dict[str, Any],
    projection: dict[str, Any] | None,
    *,
    fallback_index: int,
) -> ProjectionGroupDescriptor:
    """Return stable WBS-group identity for one projected KTP item."""
    projection = projection or {}
    stage_instance_id = _text(projection.get("target_stage_instance_id"))
    base_key = _text(raw_group.get("section_key")) or f"group-{fallback_index}"
    key = f"stage-instance:{stage_instance_id}" if stage_instance_id else f"base:{base_key}"

    stage_number = _text(projection.get("target_stage_number"))
    stage_title = _text(projection.get("target_stage_title"))
    base_title = _text(raw_group.get("title")) or f"Группа {fallback_index}"
    title = base_title
    if stage_title:
        title = stage_title

    projected_sort = _float(projection.get("target_stage_sort_order"))
    base_sort = _float(raw_group.get("sort_order")) or float(fallback_index)
    sort_order = projected_sort if projected_sort is not None else base_sort

    return ProjectionGroupDescriptor(
        key=key,
        title=title,
        sort_order=sort_order,
        stage_instance_id=stage_instance_id,
        template_stage_number=_text(projection.get("target_template_stage_number"))
        or _text(raw_group.get("template_stage_number"))
        or _text(raw_group.get("work_stage_number")),
        stage_number=stage_number or _text(raw_group.get("work_stage_number")),
        canonical_stage_id=_text(projection.get("canonical_stage_id"))
        or _text(raw_group.get("canonical_stage_id")),
        floor_number=_int(projection.get("floor_number")),
        floor_kind=_text(projection.get("floor_kind")),
        floor_label=_text(projection.get("floor_label")),
        floor_component=_text(projection.get("floor_component")),
        component_role=_text(projection.get("component_role")),
    )


def projection_metadata(projection: dict[str, Any] | None) -> dict[str, Any]:
    """Normalized stage/operation metadata copied to KTP and Gantt rows."""
    projection = projection or {}
    return {
        "source_row_key": projection.get("source_row_key"),
        "projection_id": projection.get("projection_id"),
        "stage_instance_id": projection.get("target_stage_instance_id"),
        "template_stage_number": projection.get("target_template_stage_number"),
        "stage_number": projection.get("target_stage_number"),
        "canonical_stage_id": projection.get("canonical_stage_id"),
        "floor_number": projection.get("floor_number"),
        "floor_kind": projection.get("floor_kind"),
        "floor_label": projection.get("floor_label"),
        "floor_component": projection.get("floor_component"),
        "component_role": projection.get("component_role"),
        "operation_code": projection.get("operation_code"),
        "operation_package_code": projection.get("operation_package_code"),
        "semantic_stage_option_id": projection.get("semantic_stage_option_id"),
        "stage_option_source": projection.get("stage_option_source"),
        "work_scope_key": projection.get("work_scope_key"),
        "applicability_hash": projection.get("applicability_hash"),
        "applicability_hash_version": projection.get("applicability_hash_version"),
        "applicability_schema_version": projection.get("applicability_schema_version"),
        "quantity_policy_mode": projection.get("quantity_policy_mode"),
    }


def catalog_labor_for_projection(
    estimate: Any,
    projection: dict[str, Any] | None,
    *,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    """Calculate projection-specific labour from an approved/user rate.

    ``resolved_labor_hours`` stored on the Estimate cannot be copied to every
    floor projection because the quantities can differ.  We therefore reuse
    the normalized rate value and ``norm_base_quantity`` for each projection.
    Preliminary rates with ``rate_auto_applicable=false`` remain review-only.
    """
    raw = _get(estimate, "raw_data", {})
    raw = raw if isinstance(raw, dict) else {}
    projection = projection or {}
    quantity = _float(projection.get("quantity"))
    if quantity is None:
        quantity = _float(_get(estimate, "quantity"))

    rate_auto = bool(raw.get("rate_auto_applicable"))
    requires_input = bool(raw.get("rate_requires_user_input"))
    rate_needs_review = bool(raw.get("rate_needs_review"))
    labor_per_norm = _float(raw.get("labor_hours_per_unit_avg"))
    norm_base = _float(raw.get("norm_base_quantity")) or 1.0
    template = _text(projection.get("target_template_stage_number")) or _text(raw.get("template_stage_number"))
    brick_house_projection = bool(template and template.startswith(BRICK_HOUSE_STAGE_PREFIX))
    has_rate_contract = any(
        key in raw
        for key in (
            "rate_auto_applicable", "rate_needs_review", "rate_requires_user_input",
            "selected_rate_item_id", "source_rate_id", "labor_hours_per_unit_avg",
        )
    )
    override_id = _text(raw.get("user_work_rate_override_id"))
    override_owner_id = _text(raw.get("user_work_rate_override_owner_id"))
    if override_id and (
        not owner_user_id
        or not override_owner_id
        or override_owner_id != str(owner_user_id)
    ):
        requires_input = True

    if requires_input:
        return {
            "labor_hours": None,
            "norm_source": None,
            "norm_kind": None,
            "norm_value": None,
            "norm_unit": None,
            "norm_ref": None,
            "needs_review": True,
            "review_reason": "user_rate_input_required",
        }
    if not has_rate_contract and brick_house_projection:
        return {
            "labor_hours": None,
            "norm_source": None,
            "norm_kind": None,
            "norm_value": None,
            "norm_unit": None,
            "norm_ref": None,
            "needs_review": True,
            "review_reason": "rate_not_resolved_for_gpr",
        }
    if not rate_auto or rate_needs_review or labor_per_norm is None or quantity is None:
        review = bool(rate_needs_review or (brick_house_projection and not rate_auto))
        return {
            "labor_hours": None,
            "norm_source": None,
            "norm_kind": None,
            "norm_value": None,
            "norm_unit": None,
            "norm_ref": None,
            "needs_review": review,
            "review_reason": raw.get("rate_review_reason") or (
                "rate_not_auto_applicable" if review else None
            ),
        }

    labor_hours = quantity / norm_base * labor_per_norm
    per_unit = labor_per_norm / norm_base
    return {
        "labor_hours": float(labor_hours),
        "norm_source": raw.get("resolved_labor_source") or raw.get("rate_selection_source") or "rate_catalog",
        "norm_kind": "norm_time",
        "norm_value": float(per_unit),
        "norm_unit": raw.get("rate_unit_code") or _get(estimate, "unit"),
        "norm_ref": raw.get("source_rate_id") or raw.get("selected_rate_item_id"),
        "needs_review": False,
        "review_reason": None,
    }


def is_brick_house_floor_group(group: Any) -> bool:
    template = _text(_get(group, "template_stage_number"))
    return bool(template and template.startswith(BRICK_HOUSE_STAGE_PREFIX))


def _template_num(group: Any) -> int | None:
    template = _text(_get(group, "template_stage_number"))
    if not template or not template.startswith(BRICK_HOUSE_STAGE_PREFIX):
        return None
    try:
        return int(template.rsplit(".", 1)[-1])
    except ValueError:
        return None


def _group_floor(group: Any) -> int | None:
    return _int(_get(group, "floor_number"))


def _dedupe_edges(edges: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for group_id, depends_on in edges:
        edge = (str(group_id), str(depends_on))
        if edge[0] == edge[1] or edge in seen:
            continue
        seen.add(edge)
        result.append(edge)
    return tuple(result)


def build_brick_house_floor_dependencies(groups: Iterable[Any]) -> FloorDependencyReport:
    """Build the normative variant-2.7 structural graph.

    The graph follows the v9 contract: basement lintels and slab are explicit,
    partitions form a parallel branch, and the roof branch is joined with the
    last-floor partitions only by a synthetic completion milestone.
    """
    groups = list(groups)
    floor_groups = [g for g in groups if is_brick_house_floor_group(g)]
    if not floor_groups:
        return FloorDependencyReport(applicable=False, edges=())

    by_template_floor: dict[tuple[int, int | None], Any] = {}
    unresolved: list[str] = []
    for group in floor_groups:
        template = _template_num(group)
        group_id = _text(_get(group, "id"))
        if template is None or not group_id:
            if group_id:
                unresolved.append(group_id)
            continue
        key = (template, _group_floor(group))
        if key in by_template_floor:
            unresolved.append(group_id)
            continue
        by_template_floor[key] = group

    def gid(template: int, floor: int | None = None) -> str | None:
        group = by_template_floor.get((template, floor))
        if group is None and floor is None:
            matches = [value for (number, _floor), value in by_template_floor.items() if number == template]
            if len(matches) == 1:
                group = matches[0]
        return _text(_get(group, "id")) if group is not None else None

    edges: list[tuple[str, str]] = []

    # Preserve the common pre-structural contour but keep the basement slab out
    # of the generic numeric chain: its mandatory predecessor is floor-0 lintels.
    pre_keys = sorted(
        (key for key in by_template_floor if key[0] <= 6),
        key=lambda key: (
            _float(_get(by_template_floor[key], "sort_order")) or float(key[0]),
            key[0],
            -1 if key[1] is None else key[1],
        ),
    )
    pre = [by_template_floor[key] for key in pre_keys]
    for previous, current in zip(pre, pre[1:]):
        edges.append((_text(_get(current, "id")) or "", _text(_get(previous, "id")) or ""))
    last_pre = _text(_get(pre[-1], "id")) if pre else None

    basement_walls = gid(3, 0) or gid(3, None)
    basement_lintels = gid(9, 0)
    basement_slab = gid(7, 0) or gid(7, None)
    basement_partitions = gid(11, 0)
    if basement_lintels and basement_walls:
        edges.append((basement_lintels, basement_walls))
    if basement_slab:
        if basement_lintels:
            edges.append((basement_slab, basement_lintels))
        if last_pre and last_pre not in {basement_walls, basement_lintels}:
            edges.append((basement_slab, last_pre))
    if basement_partitions and basement_slab:
        edges.append((basement_partitions, basement_slab))

    floor_numbers = sorted({
        floor for template, floor in by_template_floor
        if 8 <= template <= 11 and floor is not None and floor >= 1
    })
    previous_slab: str | None = basement_slab
    last_structural: list[str] = []
    for floor in floor_numbers:
        walls = gid(8, floor)
        lintels = gid(9, floor)
        slab = gid(10, floor)
        partitions = gid(11, floor)

        if walls:
            predecessor = previous_slab or last_pre
            if predecessor:
                edges.append((walls, predecessor))
        if lintels and walls:
            edges.append((lintels, walls))
        if slab:
            predecessor = lintels or walls
            if predecessor:
                edges.append((slab, predecessor))
        if partitions:
            predecessor = slab or lintels or walls
            if predecessor:
                edges.append((partitions, predecessor))

        if slab:
            previous_slab = slab
        last_structural = [x for x in (slab, lintels, walls, partitions) if x]

    terminal = gid(12, None)
    last_floor = floor_numbers[-1] if floor_numbers else None
    last_partitions = gid(11, last_floor) if last_floor is not None else basement_partitions
    if terminal:
        predecessor = None
        if last_floor is not None:
            predecessor = gid(10, last_floor) or gid(9, last_floor) or gid(8, last_floor)
        predecessor = predecessor or basement_slab or (last_structural[0] if last_structural else last_pre)
        if predecessor:
            edges.append((terminal, predecessor))

    roof = gid(14, None)
    if roof:
        predecessor = terminal or (last_structural[0] if last_structural else basement_slab or last_pre)
        if predecessor:
            edges.append((roof, predecessor))

    windows = gid(15, None)
    if windows:
        predecessor = roof or terminal or (last_structural[0] if last_structural else last_pre)
        if predecessor:
            edges.append((windows, predecessor))

    insulation = gid(13, None)
    if insulation:
        for predecessor in (roof, windows):
            if predecessor:
                edges.append((insulation, predecessor))
        if not roof and not windows:
            predecessor = terminal or (last_structural[0] if last_structural else last_pre)
            if predecessor:
                edges.append((insulation, predecessor))

    facade = gid(16, None)
    if facade:
        predecessors = [x for x in (insulation, windows, roof) if x]
        if not predecessors:
            predecessor = terminal or (last_structural[0] if last_structural else last_pre)
            predecessors = [predecessor] if predecessor else []
        edges.extend((facade, predecessor) for predecessor in predecessors)

    milestone_waits = _dedupe_ids(x for x in (last_partitions, roof) if x)
    milestone = StructuralCompletionMilestone(
        stage_instance_id=STRUCTURAL_COMPLETION_STAGE_INSTANCE_ID,
        task_kind="milestone",
        duration=0,
        wait_group_ids=milestone_waits,
    ) if milestone_waits else None

    return FloorDependencyReport(
        applicable=True,
        edges=_dedupe_edges(edge for edge in edges if edge[0] and edge[1]),
        unresolved_group_ids=tuple(unresolved),
        milestone=milestone,
    )


def _dedupe_ids(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def sequence_is_acyclic(groups: Iterable[Any], edges: Iterable[tuple[str, str]]) -> bool:
    ids = {_text(_get(g, "id")) for g in groups}
    ids.discard(None)
    preds: dict[str, set[str]] = {group_id: set() for group_id in ids}
    for group_id, depends_on in edges:
        if group_id in preds and depends_on in preds:
            preds[group_id].add(depends_on)
    remaining = set(preds)
    while remaining:
        ready = {node for node in remaining if not (preds[node] & remaining)}
        if not ready:
            return False
        remaining -= ready
    return True
