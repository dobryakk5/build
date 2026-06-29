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
    sort_order: int | None,
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
LOCKED_WBS_SEQUENCE_SCHEMA_V1 = "1.0.0"


def expected_total_stage_instance_count(params: BuildingParams) -> int:
    """Return the frozen variant-2.7 formula ``10 + 4B + 4F - M``."""
    return 10 + 4 * int(params.has_basement) + 4 * params.floors_count - int(params.has_mansard)


def expected_locked_stage_instance_count(params: BuildingParams) -> int:
    """Return the locked variant-2.7 formula ``11 + 2B + 3F - M``."""
    return (
        11
        + 2 * int(params.has_basement)
        + 3 * params.floors_count
        - int(params.has_mansard)
    )


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


def _require_sequence_stage(
    registry: Mapping[str, dict[str, Any]],
    stage_template: Any,
) -> dict[str, Any]:
    number = str(stage_template or "").strip()
    if not number:
        raise FloorStructureContractError(
            "wbs_stage_template_required",
            "Для шага не указан stage_template.",
        )
    stage = registry.get(number)
    if stage is None:
        raise FloorStructureContractError(
            "wbs_stage_template_missing",
            f"Шаблон этапа {number} отсутствует.",
        )
    return stage


def _component_order(value: Any) -> int:
    if isinstance(value, bool):
        raise FloorStructureContractError(
            "invalid_component_order", "component_order должен быть положительным целым числом."
        )
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise FloorStructureContractError(
            "invalid_component_order", "component_order должен быть положительным целым числом."
        ) from exc
    if result <= 0:
        raise FloorStructureContractError(
            "invalid_component_order", "component_order должен быть положительным целым числом."
        )
    return result


def _sequence_floor_range(value: Any, params: BuildingParams) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise FloorStructureContractError(
            "invalid_wbs_floor_range", "Диапазон этажей должен быть объектом."
        )
    first = value.get("from")
    to_parameter = str(value.get("to_parameter") or "")
    if isinstance(first, bool) or first != 1 or to_parameter != "floors_count":
        raise FloorStructureContractError(
            "invalid_wbs_floor_range",
            "Поддерживается только диапазон from=1, to_parameter=floors_count.",
        )
    if params.floors_count < 1:
        raise FloorStructureContractError(
            "invalid_wbs_floor_range", "floors_count должен быть не меньше 1."
        )
    return 1, params.floors_count


def _condition_matches(condition: Any, params: BuildingParams) -> bool:
    if not isinstance(condition, Mapping):
        raise FloorStructureContractError(
            "invalid_wbs_sequence_step", "condition должен быть объектом."
        )
    parameter = str(condition.get("parameter") or "")
    if parameter not in {"has_basement", "has_mansard", "floors_count"}:
        raise FloorStructureContractError(
            "unsupported_wbs_condition_parameter",
            f"Неподдерживаемый параметр условия: {parameter or '<empty>'}.",
        )
    return getattr(params, parameter) == condition.get("equals")


def _aggregate_floors_instance(
    stage: dict[str, Any],
    *,
    step_key: str,
    params: BuildingParams,
) -> dict[str, Any]:
    first_floor = 1
    last_floor = params.floors_count
    floor_numbers = list(range(first_floor, last_floor + 1))
    floor_label = "1 этаж" if last_floor == 1 else f"Этажи 1–{last_floor}"
    title = "Устройство внутренних перегородок — " + floor_label.lower()
    instance_suffix = f"aggregate:floors:{first_floor}-{last_floor}:{step_key}"
    instance = _instance(
        stage,
        number=f"{stage['number']}.AGG",
        instance_suffix=instance_suffix,
        floor=None,
        sort_order=None,
        title=title,
        floor_component="partitions",
        component_order=40,
    )
    instance.update(
        {
            "floor_number": None,
            "floor_kind": "aggregate",
            "floor_label": floor_label,
            "aggregation_mode": "aggregate_floors",
            "aggregate_floor_numbers": floor_numbers,
        }
    )
    return instance


def expand_sequence_step(
    step: Mapping[str, Any],
    *,
    registry: Mapping[str, dict[str, Any]],
    params: BuildingParams,
    variant_number: str,
) -> list[dict[str, Any]]:
    kind = str(step.get("kind") or "")
    step_key = str(step.get("key") or "").strip()
    if kind == "stage":
        stage = _require_sequence_stage(registry, step.get("stage_template"))
        return [
            _instance(
                stage,
                number=str(stage.get("number") or ""),
                instance_suffix=f"global:{step_key}",
                floor=None,
                sort_order=None,
            )
        ]

    if kind == "conditional_stage":
        if not _condition_matches(step.get("condition"), params):
            return []
        stage = _require_sequence_stage(registry, step.get("stage_template"))
        floor_context = str(step.get("floor_context") or "")
        if floor_context not in {"", "basement"}:
            raise FloorStructureContractError(
                "invalid_wbs_sequence_step", f"Неподдерживаемый floor_context: {floor_context}."
            )
        floor = FloorUnit(0, "basement", "Цоколь, этаж 0") if floor_context == "basement" else None
        order = _component_order(step.get("component_order")) if step.get("component_order") is not None else None
        return [
            _instance(
                stage,
                number=str(stage.get("number") or ""),
                instance_suffix="floor:0" if floor else f"global:{step_key}",
                floor=floor,
                sort_order=None,
                floor_component=(stage.get("floor_binding") or {}).get("component"),
                component_order=order,
            )
        ]

    if kind == "floor_loop":
        first, last = _sequence_floor_range(step.get("floors"), params)
        components = step.get("components")
        if not isinstance(components, list) or not components:
            raise FloorStructureContractError(
                "floor_loop_components_required", "Для floor_loop требуется массив components."
            )
        seen_components: set[str] = set()
        seen_orders: set[int] = set()
        normalized: list[tuple[str, int, dict[str, Any], bool]] = []
        for raw_component in components:
            if not isinstance(raw_component, Mapping):
                raise FloorStructureContractError(
                    "invalid_wbs_sequence_step", "Компонент floor_loop должен быть объектом."
                )
            component = str(raw_component.get("component") or "").strip()
            if not component:
                raise FloorStructureContractError(
                    "invalid_wbs_sequence_step", "Для компонента не указан component."
                )
            if component in seen_components:
                raise FloorStructureContractError(
                    "duplicate_floor_loop_component", f"Компонент {component} повторяется."
                )
            seen_components.add(component)
            order = _component_order(raw_component.get("component_order"))
            if order in seen_orders:
                raise FloorStructureContractError(
                    "invalid_component_order", f"component_order {order} повторяется."
                )
            seen_orders.add(order)
            omit = bool(raw_component.get("omit_on_mansard_last_floor", False))
            if omit and component != "slab":
                raise FloorStructureContractError(
                    "invalid_wbs_sequence_step",
                    "omit_on_mansard_last_floor поддерживается только для slab.",
                )
            normalized.append(
                (
                    component,
                    order,
                    _require_sequence_stage(registry, raw_component.get("stage_template")),
                    omit,
                )
            )
        normalized.sort(key=lambda item: item[1])
        result: list[dict[str, Any]] = []
        for floor_number in range(first, last + 1):
            is_mansard = params.has_mansard and floor_number == params.floors_count
            floor = FloorUnit(
                floor_number,
                "mansard" if is_mansard else "standard",
                f"Мансарда, {floor_number} этаж" if is_mansard else f"{floor_number} этаж",
            )
            for component, order, stage, omit in normalized:
                if is_mansard and omit:
                    continue
                result.append(
                    _instance(
                        stage,
                        number=f"{variant_number}.F{floor_number}.{order:02d}",
                        instance_suffix=f"floor:{floor_number}",
                        floor=floor,
                        sort_order=None,
                        title=f"{stage.get('title')} — {floor.floor_label}",
                        floor_component=component,
                        component_order=order,
                    )
                )
        return result

    if kind == "aggregate_floors":
        _sequence_floor_range(step.get("floors"), params)
        if str(step.get("aggregation_mode") or "") != "single_group":
            raise FloorStructureContractError(
                "invalid_wbs_sequence_step", "aggregate_floors поддерживает только single_group."
            )
        _component_order(step.get("component_order"))
        stage = _require_sequence_stage(registry, step.get("stage_template"))
        return [_aggregate_floors_instance(stage, step_key=step_key, params=params)]

    raise FloorStructureContractError(
        "unsupported_wbs_sequence_step_kind",
        f"Неподдерживаемый kind шага: {kind or '<empty>'}.",
    )


def _assign_classification_anchors(
    stage_instances: list[dict[str, Any]],
    *,
    floor_assignment: Mapping[str, Any],
) -> None:
    by_template: dict[str, list[dict[str, Any]]] = {}
    for stage in stage_instances:
        template = str(stage.get("template_stage_number") or "")
        by_template.setdefault(template, []).append(stage)
    for stages in by_template.values():
        ordered = sorted(
            stages,
            key=lambda item: (
                int(item.get("sort_order") or 0),
                str(item.get("stage_instance_id") or ""),
            ),
        )
        above_ground = [
            stage
            for stage in ordered
            if isinstance(stage.get("floor_number"), int) and stage.get("floor_number") >= 1
        ]
        anchor = (
            min(
                above_ground,
                key=lambda item: (
                    int(item["floor_number"]),
                    int(item.get("sort_order") or 0),
                ),
            )
            if above_ground
            else ordered[0]
        )
        anchor_id = str(anchor.get("stage_instance_id") or "")
        if not anchor_id:
            raise FloorStructureContractError(
                "classification_anchor_missing", "У anchor отсутствует stage_instance_id."
            )
        for stage in ordered:
            stage.update(
                {
                    "floor_assignment_source": floor_assignment.get("source") or "building_params",
                    "use_estimate_text_floor_reference": bool(
                        floor_assignment.get("use_estimate_text_reference", False)
                    ),
                    "classification_mode": floor_assignment.get("classification_mode")
                    or "template_anchor",
                    "classification_candidate": stage is anchor,
                    "classification_anchor_stage_instance_id": anchor_id,
                    "projection_target": True,
                }
            )


def _validate_locked_stage_instances(
    stage_instances: Sequence[Mapping[str, Any]], params: BuildingParams
) -> None:
    by_template: dict[str, list[Mapping[str, Any]]] = {}
    for stage in stage_instances:
        instance_id = str(stage.get("stage_instance_id") or "")
        if not instance_id:
            raise FloorStructureContractError(
                "stage_instance_id_required", "Generated stage instance has no ID."
            )
        by_template.setdefault(str(stage.get("template_stage_number") or ""), []).append(stage)

    for template, stages in by_template.items():
        anchors = [stage for stage in stages if stage.get("classification_candidate") is True]
        if not anchors:
            raise FloorStructureContractError(
                "classification_anchor_missing", f"Для шаблона {template} отсутствует anchor."
            )
        if len(anchors) > 1:
            raise FloorStructureContractError(
                "duplicate_classification_anchor", f"Для шаблона {template} найдено несколько anchors."
            )
        if any(stage.get("projection_target") is not True for stage in stages):
            raise FloorStructureContractError(
                "invalid_wbs_sequence_step", "Все generated instances должны быть projection targets."
            )

    floors = set(range(1, params.floors_count + 1))
    for template in ("2.7.8", "2.7.9"):
        actual = {stage.get("floor_number") for stage in by_template.get(template, [])}
        if actual != floors:
            raise FloorStructureContractError(
                "locked_stage_instance_count_mismatch",
                f"Шаблон {template} должен существовать на каждом надземном этаже.",
            )
    slab_floors = {stage.get("floor_number") for stage in by_template.get("2.7.10", [])}
    expected_slabs = floors - ({params.floors_count} if params.has_mansard else set())
    if slab_floors != expected_slabs:
        raise FloorStructureContractError(
            "locked_stage_instance_count_mismatch", "Состав перекрытий не соответствует параметрам здания."
        )
    aggregate = by_template.get("2.7.11", [])
    if len(aggregate) != 1 or aggregate[0].get("floor_kind") != "aggregate":
        raise FloorStructureContractError(
            "locked_stage_instance_count_mismatch", "Должен существовать один aggregate перегородок."
        )
    basement_templates = {
        str(stage.get("template_stage_number") or "")
        for stage in stage_instances
        if stage.get("floor_number") == 0
    }
    expected_basement = {"2.7.3", "2.7.7"} if params.has_basement else set()
    if basement_templates != expected_basement:
        raise FloorStructureContractError(
            "locked_stage_instance_count_mismatch", "Состав цокольных стадий некорректен."
        )


def build_locked_wbs_sequence(
    variant: dict[str, Any],
    params: BuildingParams,
) -> list[dict[str, Any]]:
    schema = variant.get("wbs_sequence_schema")
    if schema is None:
        raise FloorStructureContractError(
            "wbs_sequence_schema_required", "Для locked WBS требуется wbs_sequence_schema."
        )
    if not isinstance(schema, Mapping):
        raise FloorStructureContractError(
            "unsupported_wbs_sequence_schema", "wbs_sequence_schema должен быть объектом."
        )
    if str(schema.get("schema_version") or "") != LOCKED_WBS_SEQUENCE_SCHEMA_V1:
        raise FloorStructureContractError(
            "unsupported_wbs_sequence_schema",
            f"Неподдерживаемая версия wbs_sequence_schema: {schema.get('schema_version') or '<empty>'}.",
        )
    if str(schema.get("mode") or "") != "locked":
        raise FloorStructureContractError(
            "invalid_wbs_sequence_mode",
            "Для wbs_sequence_schema версии 1.0.0 поддерживается только mode=locked.",
        )
    floor_assignment = schema.get("floor_assignment")
    if not isinstance(floor_assignment, Mapping) or floor_assignment.get("source") != "building_params":
        raise FloorStructureContractError(
            "invalid_floor_assignment_source", "floor_assignment.source должен быть building_params."
        )
    if floor_assignment.get("use_estimate_text_reference") is not False:
        raise FloorStructureContractError(
            "invalid_floor_assignment_source", "Текстовое назначение этажа должно быть отключено."
        )
    if floor_assignment.get("classification_mode") != "template_anchor":
        raise FloorStructureContractError(
            "invalid_floor_classification_mode", "classification_mode должен быть template_anchor."
        )
    steps = schema.get("steps")
    if not isinstance(steps, list) or not steps:
        raise FloorStructureContractError(
            "wbs_sequence_steps_required", "Для locked WBS требуется непустой массив steps."
        )
    try:
        sort_order_step = int(schema.get("sort_order_step") or 1000)
    except (TypeError, ValueError) as exc:
        raise FloorStructureContractError(
            "invalid_wbs_sequence_step", "sort_order_step должен быть положительным целым числом."
        ) from exc
    if sort_order_step <= 0:
        raise FloorStructureContractError(
            "invalid_wbs_sequence_step", "sort_order_step должен быть положительным целым числом."
        )

    registry = _stage_registry(variant)
    variant_number = str(variant.get("number") or "2.7")
    result: list[dict[str, Any]] = []
    seen_step_keys: set[str] = set()
    next_sort_order = sort_order_step
    for step_index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, Mapping):
            raise FloorStructureContractError(
                "invalid_wbs_sequence_step", f"Шаг {step_index} должен быть объектом."
            )
        step_key = str(raw_step.get("key") or "").strip()
        if not step_key:
            raise FloorStructureContractError(
                "wbs_sequence_step_key_required", f"Для шага {step_index} не указан key."
            )
        if step_key in seen_step_keys:
            raise FloorStructureContractError(
                "duplicate_wbs_sequence_step_key", f"Ключ шага {step_key} повторяется."
            )
        seen_step_keys.add(step_key)
        expanded = expand_sequence_step(
            raw_step,
            registry=registry,
            params=params,
            variant_number=variant_number,
        )
        for stage in expanded:
            stage["sort_order"] = next_sort_order
            stage["sequence_index"] = len(result) + 1
            stage["sequence_step_index"] = step_index
            stage["sequence_step_key"] = step_key
            stage["sequence_mode"] = "locked"
            stage["sequence_source"] = "taxonomy_wbs_sequence_schema"
            result.append(stage)
            next_sort_order += sort_order_step

    identifiers = [str(stage.get("stage_instance_id") or "") for stage in result]
    if any(not identifier for identifier in identifiers):
        raise FloorStructureContractError(
            "stage_instance_id_required", "Generated stage instance has no ID."
        )
    if len(identifiers) != len(set(identifiers)):
        raise FloorStructureContractError(
            "duplicate_stage_instance_id", "Generated stage_instance_id values are not unique."
        )
    expected = expected_locked_stage_instance_count(params)
    if len(result) != expected:
        raise FloorStructureContractError(
            "locked_stage_instance_count_mismatch",
            f"Expected {expected} locked stage instances, generated {len(result)}.",
        )
    _assign_classification_anchors(result, floor_assignment=floor_assignment)
    _validate_locked_stage_instances(result, params)
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
    sequence_schema = variant.get("wbs_sequence_schema")
    if sequence_schema is not None:
        if not isinstance(sequence_schema, Mapping):
            raise FloorStructureContractError(
                "unsupported_wbs_sequence_schema",
                "wbs_sequence_schema должен быть объектом.",
            )
        schema_version = str(sequence_schema.get("schema_version") or "")
        if schema_version != LOCKED_WBS_SEQUENCE_SCHEMA_V1:
            raise FloorStructureContractError(
                "unsupported_wbs_sequence_schema",
                "Неподдерживаемая версия wbs_sequence_schema: "
                f"{schema_version or '<empty>'}.",
            )
        mode = str(sequence_schema.get("mode") or "")
        if mode != "locked":
            raise FloorStructureContractError(
                "invalid_wbs_sequence_mode",
                "Для wbs_sequence_schema версии 1.0.0 поддерживается только mode=locked.",
            )
        if params is None:
            raise FloorStructureContractError(
                "building_params_required", "Для locked WBS требуются параметры здания."
            )
        return build_locked_wbs_sequence(variant, params)

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
