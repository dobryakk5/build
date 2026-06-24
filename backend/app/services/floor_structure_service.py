"""Deterministic runtime expansion of project stages by building floors.

The service is data-driven: variants opt in through ``building_params_schema``
and describe templates through ``floor_structure_schema`` and ``floor_binding``.
It does not classify estimate rows or calculate quantities.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


class BuildingParamsValidationError(ValueError):
    """Stable validation error used by API/service layers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FloorStructureContractError(ValueError):
    """Raised when a versioned floor-structure taxonomy is internally invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FloorStructureIssue:
    """Stable domain issue returned by structural validators."""

    code: str
    stage_instance_ids: tuple[str, ...] = ()
    work_scope_key: str | None = None
    details: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "stage_instance_ids": list(self.stage_instance_ids),
        }
        if self.work_scope_key is not None:
            payload["work_scope_key"] = self.work_scope_key
        if self.details is not None:
            payload["details"] = deepcopy(dict(self.details))
        return payload


@dataclass(frozen=True)
class BuildingParams:
    floors_count: int
    has_basement: bool
    has_mansard: bool


@dataclass(frozen=True)
class FloorUnit:
    floor_number: int
    floor_kind: str
    floor_label: str


@dataclass(frozen=True)
class StageInstance:
    stage_instance_id: str
    number: str
    template_stage_number: str
    legacy_stage_number: str | None
    canonical_stage_id: str
    title: str
    floor_number: int | None
    floor_kind: str | None
    floor_label: str | None
    floor_component: str | None
    component_role: str | None
    component_order: int | None
    occurrence_index: int | None
    occurrence_label: str | None
    sort_order: int
    source_stage: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        payload = deepcopy(self.source_stage)
        payload.update(
            {
                "stage_instance_id": self.stage_instance_id,
                "number": self.number,
                "template_stage_number": self.template_stage_number,
                "legacy_stage_number": self.legacy_stage_number,
                "canonical_stage_id": self.canonical_stage_id,
                "title": self.title,
                "floor_number": self.floor_number,
                "floor_kind": self.floor_kind,
                "floor_label": self.floor_label,
                "floor_component": self.floor_component,
                "component_role": self.component_role,
                "component_order": self.component_order,
                "occurrence_index": self.occurrence_index,
                "occurrence_label": self.occurrence_label,
                "sort_order": self.sort_order,
            }
        )
        payload["source_stage"] = deepcopy(self.source_stage)
        return payload


def _schema(variant: dict[str, Any]) -> dict[str, Any]:
    schema = variant.get("building_params_schema")
    return schema if isinstance(schema, dict) else {}


def is_floor_structure_enabled(variant: dict[str, Any]) -> bool:
    return bool(_schema(variant).get("enabled"))


def validate_building_params(
    building_params: dict[str, Any] | None,
    variant: dict[str, Any],
) -> BuildingParams | None:
    """Validate request parameters according to the selected variant schema."""
    schema = _schema(variant)
    if not schema.get("enabled"):
        return None
    if building_params is None:
        raise BuildingParamsValidationError(
            "building_params_required",
            "Для выбранного варианта необходимо указать этажность здания.",
        )
    if not isinstance(building_params, dict):
        raise BuildingParamsValidationError(
            "invalid_building_params",
            "building_params должен быть объектом.",
        )

    allowed = {"floors_count", "has_basement", "has_mansard"}
    unknown = sorted(set(building_params) - allowed)
    if unknown:
        raise BuildingParamsValidationError(
            "unknown_building_params_fields",
            "Неизвестные параметры здания: " + ", ".join(unknown),
        )

    floors_cfg = schema.get("floors_count") if isinstance(schema.get("floors_count"), dict) else {}
    value = building_params.get("floors_count")
    if isinstance(value, bool) or not isinstance(value, int):
        raise BuildingParamsValidationError(
            "invalid_floors_count",
            "floors_count должен быть целым числом.",
        )
    minimum = int(floors_cfg.get("minimum", 1))
    maximum = int(floors_cfg.get("maximum", 100))
    if value < minimum or value > maximum:
        raise BuildingParamsValidationError(
            "floor_out_of_range",
            f"floors_count должен быть в диапазоне {minimum}..{maximum}.",
        )

    def strict_bool(name: str) -> bool:
        raw = building_params.get(name, False)
        if not isinstance(raw, bool):
            raise BuildingParamsValidationError(
                "invalid_building_params",
                f"{name} должен быть boolean.",
            )
        return raw

    return BuildingParams(
        floors_count=value,
        has_basement=strict_bool("has_basement"),
        has_mansard=strict_bool("has_mansard"),
    )


def build_floor_units(params: BuildingParams) -> list[FloorUnit]:
    units: list[FloorUnit] = []
    if params.has_basement:
        units.append(FloorUnit(0, "basement", "Цоколь, этаж 0"))
    for number in range(1, params.floors_count + 1):
        is_mansard = params.has_mansard and number == params.floors_count
        units.append(
            FloorUnit(
                number,
                "mansard" if is_mansard else "standard",
                f"Мансарда, {number} этаж" if is_mansard else f"{number} этаж",
            )
        )
    return units


def _static_instance(stage: dict[str, Any], index: int) -> dict[str, Any]:
    source = deepcopy(stage)
    canonical = str(stage.get("canonical_stage_id") or stage.get("id") or stage.get("number") or index)
    payload = deepcopy(stage)
    payload.update(
        {
            "stage_instance_id": f"{canonical}:static:{stage.get('number') or index}",
            "template_stage_number": str(stage.get("number") or ""),
            "legacy_stage_number": None,
            "floor_number": None,
            "floor_kind": None,
            "floor_label": None,
            "floor_component": None,
            "component_role": None,
            "component_order": None,
            "sort_order": (index + 1) * 1000,
            "source_stage": source,
        }
    )
    return payload


def build_static_stage_instances(variant: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _static_instance(stage, index)
        for index, stage in enumerate(variant.get("stages") or [])
        if isinstance(stage, dict)
    ]


def _instance(
    stage: dict[str, Any],
    *,
    number: str,
    instance_suffix: str,
    floor: FloorUnit | None,
    sort_order: int,
    title: str | None = None,
    floor_component: str | None = None,
    component_order: int | None = None,
) -> dict[str, Any]:
    binding = stage.get("floor_binding") if isinstance(stage.get("floor_binding"), dict) else {}
    canonical = str(stage.get("canonical_stage_id") or stage.get("id") or stage.get("number"))
    source = deepcopy(stage)
    payload = deepcopy(stage)
    payload.update(
        {
            "stage_instance_id": f"{canonical}:{instance_suffix}",
            "number": number,
            "template_stage_number": str(stage.get("number") or ""),
            "legacy_stage_number": None,
            "canonical_stage_id": canonical,
            "title": title or str(stage.get("title") or ""),
            "floor_number": floor.floor_number if floor else None,
            "floor_kind": floor.floor_kind if floor else None,
            "floor_label": floor.floor_label if floor else None,
            "floor_component": floor_component if floor_component is not None else binding.get("component"),
            "component_role": binding.get("component_role"),
            "component_order": (
                component_order
                if component_order is not None
                else (int(binding.get("component_order")) if binding.get("component_order") is not None else None)
            ),
            "occurrence_index": floor.floor_number if floor else stage.get("occurrence_index"),
            "occurrence_label": floor.floor_label if floor else stage.get("occurrence_label"),
            "sort_order": sort_order,
            "source_stage": source,
        }
    )
    return payload



DYNAMIC_FLOOR_SCHEMA_V2 = "2.0.0"


def expected_total_stage_instance_count(params: BuildingParams) -> int:
    """Return the frozen variant-2.7 formula ``10 + 4B + 4F - M``."""
    return 10 + 4 * int(params.has_basement) + 4 * params.floors_count - int(params.has_mansard)


def structural_slab_stage_count(params: BuildingParams) -> int:
    """Return basement slab plus standard above-ground slab instances."""
    return int(params.has_basement) + params.floors_count - int(params.has_mansard)


def _number_suffix(stage_number: str) -> int:
    try:
        return int(stage_number.rsplit(".", 1)[1])
    except (IndexError, ValueError) as exc:
        raise FloorStructureContractError(
            "invalid_stage_template_number",
            f"Invalid stage template number: {stage_number!r}",
        ) from exc


def _stage_registry(variant: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in variant.get("stages") or []:
        if not isinstance(raw, Mapping):
            continue
        stage = deepcopy(dict(raw))
        number = str(stage.get("number") or "")
        if not number:
            raise FloorStructureContractError(
                "stage_template_number_required",
                "Every stage template must have a number.",
            )
        if number in result:
            raise FloorStructureContractError(
                "duplicate_stage_template_number",
                f"Duplicate stage template number: {number}",
            )
        result[number] = stage
    return result


def _require_stage(
    registry: Mapping[str, dict[str, Any]],
    number: str,
    *,
    registry_name: str,
) -> dict[str, Any]:
    stage = registry.get(number)
    if stage is None:
        raise FloorStructureContractError(
            "floor_structure_stage_template_missing",
            f"{registry_name} references missing stage {number}",
        )
    return stage


def _common_sort_order(stage_number: str) -> int:
    suffix = _number_suffix(stage_number)
    # Common pre-structure stages stay before the floor blocks; facade and
    # finishing stages stay after terminal structural stages.
    return (100000 if suffix <= 6 else 900000) + suffix * 1000


def _build_stage_instances_schema_v2(
    variant: dict[str, Any],
    params: BuildingParams,
) -> list[dict[str, Any]]:
    """Build variant 2.7 instances exclusively from schema-v2 registries."""
    schema = variant.get("floor_structure_schema")
    if not isinstance(schema, Mapping):
        raise FloorStructureContractError(
            "floor_structure_schema_required",
            "floor_structure_schema must be an object.",
        )
    registry = _stage_registry(variant)
    prefix = str(variant.get("number") or "2.7")
    result: list[dict[str, Any]] = []

    common_numbers = [str(item) for item in schema.get("common_stage_templates") or []]
    if len(common_numbers) != len(set(common_numbers)):
        raise FloorStructureContractError(
            "duplicate_common_stage_template",
            "common_stage_templates contains duplicates.",
        )
    for number in common_numbers:
        stage = _require_stage(registry, number, registry_name="common_stage_templates")
        result.append(
            _instance(
                stage,
                number=number,
                instance_suffix=f"global:{number}",
                floor=None,
                sort_order=_common_sort_order(number),
            )
        )

    basement_templates = schema.get("basement_stage_templates") or {}
    basement_order = schema.get("basement_component_order") or {}
    if params.has_basement:
        floor = FloorUnit(0, "basement", "Цоколь, этаж 0")
        for component in ("walls", "lintels", "slab", "partitions"):
            stage_number = str(basement_templates.get(component) or "")
            if not stage_number:
                raise FloorStructureContractError(
                    "basement_stage_template_missing",
                    f"basement_stage_templates.{component} is required.",
                )
            order = int(basement_order.get(component) or 0)
            if order <= 0:
                raise FloorStructureContractError(
                    "basement_component_order_invalid",
                    f"basement_component_order.{component} must be positive.",
                )
            stage = _require_stage(
                registry,
                stage_number,
                registry_name=f"basement_stage_templates.{component}",
            )
            result.append(
                _instance(
                    stage,
                    number=f"{prefix}.B0.{order:02d}",
                    instance_suffix="floor:0",
                    floor=floor,
                    sort_order=500000 + order,
                    title=f"{stage.get('title')} — {floor.floor_label}",
                    floor_component=component,
                    component_order=order,
                )
            )

    standard_templates = schema.get("standard_floor_stage_templates") or {}
    mansard_rules = schema.get("mansard_rules") or {}
    omitted_on_mansard = {str(item) for item in mansard_rules.get("omit_stage_templates") or []}
    above_ground = [unit for unit in build_floor_units(params) if unit.floor_number >= 1]
    for floor in above_ground:
        for component in ("walls", "lintels", "slab", "partitions"):
            stage_number = str(standard_templates.get(component) or "")
            if not stage_number:
                raise FloorStructureContractError(
                    "standard_floor_stage_template_missing",
                    f"standard_floor_stage_templates.{component} is required.",
                )
            stage = _require_stage(
                registry,
                stage_number,
                registry_name=f"standard_floor_stage_templates.{component}",
            )
            binding = stage.get("floor_binding") if isinstance(stage.get("floor_binding"), Mapping) else {}
            if floor.floor_kind == "mansard" and (
                stage_number in omitted_on_mansard or bool(binding.get("omit_on_mansard"))
            ):
                continue
            order = int(binding.get("component_order") or 0)
            if order <= 0:
                raise FloorStructureContractError(
                    "floor_component_order_invalid",
                    f"Stage {stage_number} must define a positive component_order.",
                )
            result.append(
                _instance(
                    stage,
                    number=f"{prefix}.F{floor.floor_number}.{order:02d}",
                    instance_suffix=f"floor:{floor.floor_number}",
                    floor=floor,
                    sort_order=600000 + floor.floor_number * 1000 + order,
                    title=f"{stage.get('title')} — {floor.floor_label}",
                    floor_component=component,
                    component_order=order,
                )
            )

    if not above_ground:
        raise FloorStructureContractError(
            "above_ground_floor_required",
            "At least one above-ground floor is required.",
        )
    last_floor = above_ground[-1]
    terminal_templates = schema.get("terminal_stage_templates") or {}
    terminal_sequence = [
        ("armopoyas_and_mauerlat", 50),
        ("roof", 60),
    ]
    for terminal_key, fallback_order in terminal_sequence:
        stage_number = str(terminal_templates.get(terminal_key) or "")
        if not stage_number:
            raise FloorStructureContractError(
                "terminal_stage_template_missing",
                f"terminal_stage_templates.{terminal_key} is required.",
            )
        stage = _require_stage(
            registry,
            stage_number,
            registry_name=f"terminal_stage_templates.{terminal_key}",
        )
        binding = stage.get("floor_binding") if isinstance(stage.get("floor_binding"), Mapping) else {}
        order = int(binding.get("component_order") or fallback_order)
        result.append(
            _instance(
                stage,
                number=f"{prefix}.T{last_floor.floor_number}.{order:02d}",
                instance_suffix=f"terminal:{last_floor.floor_number}",
                floor=last_floor,
                sort_order=800000 + order,
                component_order=order,
            )
        )

    result.sort(key=lambda item: (int(item.get("sort_order") or 0), str(item.get("number") or "")))
    identifiers = [str(item.get("stage_instance_id") or "") for item in result]
    if len(identifiers) != len(set(identifiers)):
        raise FloorStructureContractError(
            "duplicate_stage_instance_id",
            "Generated stage_instance_id values are not unique.",
        )
    expected = expected_total_stage_instance_count(params)
    if len(result) != expected:
        raise FloorStructureContractError(
            "stage_instance_count_mismatch",
            f"Expected {expected} stage instances, generated {len(result)}.",
        )
    blocking = [
        issue
        for issue in validate_dynamic_floor_stage_instances(result)
        if issue.code in {"basement_wall_stage_duplicated", "basement_generic_slab_duplicated"}
    ]
    if blocking:
        raise FloorStructureContractError(blocking[0].code, "Generated floor structure is invalid.")
    return result


def _instance_ids(items: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(str(item.get("stage_instance_id") or "") for item in items)


def validate_dynamic_floor_stage_instances(
    stage_instances: Sequence[Mapping[str, Any]],
) -> list[FloorStructureIssue]:
    """Validate structural invariants without preview, worker or persistence."""
    issues: list[FloorStructureIssue] = []
    basement_walls = [
        item
        for item in stage_instances
        if item.get("floor_number") == 0 and item.get("template_stage_number") == "2.7.3"
    ]
    generic_basement_walls = [
        item
        for item in stage_instances
        if item.get("floor_number") == 0 and item.get("template_stage_number") == "2.7.8"
    ]
    if basement_walls and generic_basement_walls:
        issues.append(
            FloorStructureIssue(
                "basement_wall_stage_duplicated",
                _instance_ids([*basement_walls, *generic_basement_walls]),
            )
        )

    basement_slabs = [
        item
        for item in stage_instances
        if item.get("floor_number") == 0 and item.get("template_stage_number") == "2.7.7"
    ]
    generic_basement_slabs = [
        item
        for item in stage_instances
        if item.get("floor_number") == 0 and item.get("template_stage_number") == "2.7.10"
    ]
    if len(basement_slabs) > 1 or generic_basement_slabs:
        issues.append(
            FloorStructureIssue(
                "basement_generic_slab_duplicated",
                _instance_ids([*basement_slabs, *generic_basement_slabs]),
            )
        )

    basement_partitions = [
        item
        for item in stage_instances
        if item.get("floor_number") == 0 and item.get("template_stage_number") == "2.7.11"
    ]
    wall_scopes = {
        str(item.get("work_scope_key"))
        for item in basement_walls
        if item.get("work_scope_key")
    }
    partition_scopes = {
        str(item.get("work_scope_key"))
        for item in basement_partitions
        if item.get("work_scope_key")
    }
    for scope in sorted(wall_scopes & partition_scopes):
        related = [
            item
            for item in [*basement_walls, *basement_partitions]
            if str(item.get("work_scope_key") or "") == scope
        ]
        issues.append(
            FloorStructureIssue(
                "basement_wall_scope_conflict",
                _instance_ids(related),
                work_scope_key=scope,
            )
        )

    for item in stage_instances:
        if item.get("operation_resolution_status") != "resolved":
            continue
        selected = item.get("semantic_stage_option_ids")
        if selected is None and item.get("semantic_stage_option_id") is not None:
            selected = [item.get("semantic_stage_option_id")]
        selected_values = [value for value in (selected or []) if value]
        operations = [value for value in (item.get("resolved_operation_codes") or []) if value]
        if selected_values and not operations and not bool(item.get("recommendation_only")):
            issues.append(
                FloorStructureIssue(
                    "stage_instance_has_no_operations",
                    _instance_ids([item]),
                    details={"semantic_stage_option_ids": selected_values},
                )
            )
    return issues


def build_stage_instances(
    variant: dict[str, Any],
    params: BuildingParams | None,
) -> list[dict[str, Any]]:
    """Expand one already-loaded variant into deterministic runtime stages."""
    if params is None or not is_floor_structure_enabled(variant):
        return build_static_stage_instances(variant)

    floor_schema = variant.get("floor_structure_schema")
    if isinstance(floor_schema, Mapping) and floor_schema.get("schema_version") == DYNAMIC_FLOOR_SCHEMA_V2:
        return _build_stage_instances_schema_v2(variant, params)

    stages = [stage for stage in (variant.get("stages") or []) if isinstance(stage, dict)]
    per_floor = [
        (index, stage)
        for index, stage in enumerate(stages)
        if (stage.get("floor_binding") or {}).get("repeat_policy") == "per_floor"
    ]
    if not per_floor:
        return build_static_stage_instances(variant)

    first_dynamic = min(index for index, _ in per_floor)
    last_dynamic = max(index for index, _ in per_floor)
    templates = sorted(
        (stage for _, stage in per_floor),
        key=lambda item: int((item.get("floor_binding") or {}).get("component_order") or 0),
    )
    above_ground = [unit for unit in build_floor_units(params) if unit.floor_number > 0]
    last_floor = above_ground[-1]
    prefix = str(variant.get("number") or "F")
    result: list[dict[str, Any]] = []

    def append_non_dynamic(index: int, stage: dict[str, Any], after: bool) -> None:
        binding = stage.get("floor_binding") if isinstance(stage.get("floor_binding"), dict) else {}
        policy = binding.get("repeat_policy")
        component_order = int(binding.get("component_order") or 0)
        base_sort = 900000 if after else 100000
        if policy == "basement_only":
            if not params.has_basement:
                return
            floor = FloorUnit(0, "basement", "Цоколь, этаж 0")
            result.append(
                _instance(
                    stage,
                    number=f"{prefix}.B0.{component_order:02d}",
                    instance_suffix="floor:0",
                    floor=floor,
                    sort_order=base_sort + (index + 1) * 1000 + component_order,
                    title=f"{stage.get('title')} — {floor.floor_label}",
                )
            )
            return
        if policy == "single_terminal":
            result.append(
                _instance(
                    stage,
                    number=f"{prefix}.T{last_floor.floor_number}.{component_order:02d}",
                    instance_suffix=f"terminal:{last_floor.floor_number}",
                    floor=last_floor,
                    sort_order=base_sort + (index + 1) * 1000 + component_order,
                )
            )
            return
        result.append(
            _instance(
                stage,
                number=str(stage.get("number") or ""),
                instance_suffix=f"global:{stage.get('number') or index}",
                floor=None,
                sort_order=base_sort + (index + 1) * 1000,
            )
        )

    for index, stage in enumerate(stages[:first_dynamic]):
        append_non_dynamic(index, stage, after=False)

    omitted_on_mansard = set(
        ((variant.get("floor_structure_schema") or {}).get("mansard_rules") or {}).get(
            "omit_stage_templates", []
        )
    )
    for floor in above_ground:
        for stage in templates:
            binding = stage.get("floor_binding") or {}
            if floor.floor_kind == "mansard" and (
                bool(binding.get("omit_on_mansard"))
                or str(stage.get("number")) in omitted_on_mansard
            ):
                continue
            order = int(binding.get("component_order") or 0)
            result.append(
                _instance(
                    stage,
                    number=f"{prefix}.F{floor.floor_number}.{order:02d}",
                    instance_suffix=f"floor:{floor.floor_number}",
                    floor=floor,
                    sort_order=600000 + floor.floor_number * 1000 + order,
                    title=f"{stage.get('title')} — {floor.floor_label}",
                )
            )

    for index, stage in enumerate(stages[last_dynamic + 1 :], start=last_dynamic + 1):
        append_non_dynamic(index, stage, after=True)

    return sorted(result, key=lambda item: (int(item.get("sort_order") or 0), str(item.get("number") or "")))


def structure_summary(params: BuildingParams) -> str:
    parts: list[str] = []
    if params.has_basement:
        parts.append("цоколь")
    parts.append(f"{params.floors_count} надземных этажей")
    result = "Структура здания: " + " + ".join(parts) + "."
    if params.has_mansard:
        result += " Последний этаж: мансарда."
    return result
