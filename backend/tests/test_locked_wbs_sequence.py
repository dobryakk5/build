from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.floor_structure_service import (
    BuildingParams,
    FloorStructureContractError,
    build_stage_instances,
    expected_locked_stage_instance_count,
)
from app.services.ktp_floor_sequence_service import build_locked_sequence_dependencies
from app.services.ktp_sequence_policy_service import SequencePolicy, sequence_policy_from_snapshot
from app.services.quantity_projection_service import enrich_quantity_projections
from app.services.stage_classifier import StageClassifier
from app.services.taxonomy_snapshot_service import build_immutable_taxonomy_snapshot
from app.services.work_taxonomy_service import get_sequential_scoring_policy


DICTIONARY = Path(__file__).resolve().parents[1] / "app" / "data" / "construction_work_dictionary_v6_5_1.json"


def _variant() -> dict:
    payload = json.loads(DICTIONARY.read_text(encoding="utf-8"))
    return next(
        variant
        for estimate_type in payload["project_hierarchy"]["estimate_types"]
        for variant in estimate_type["project_variants"]
        if variant["id"] == "residential_construction_kirpichnye_doma"
    )


def _legacy_variant() -> dict:
    path = DICTIONARY.with_name("construction_work_dictionary_v6_5_0.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return next(
        variant
        for estimate_type in payload["project_hierarchy"]["estimate_types"]
        for variant in estimate_type["project_variants"]
        if variant["id"] == "residential_construction_kirpichnye_doma"
    )


def _stages(*, floors: int = 2, basement: bool = True, mansard: bool = False) -> list[dict]:
    return build_stage_instances(
        _variant(),
        BuildingParams(floors, basement, mansard),
    )


def test_locked_sequence_two_floors_with_basement_exact_order() -> None:
    stages = _stages()
    assert len(stages) == 19
    assert [stage["template_stage_number"] for stage in stages] == [
        "2.7.1", "2.7.2", "2.7.3", "2.7.4", "2.7.5", "2.7.6", "2.7.7",
        "2.7.8", "2.7.9", "2.7.10", "2.7.8", "2.7.9", "2.7.10",
        "2.7.11", "2.7.12", "2.7.13", "2.7.14", "2.7.15", "2.7.16",
    ]
    assert [stage["sort_order"] for stage in stages] == list(range(1000, 20000, 1000))
    assert [stage["title"] for stage in stages] == [
        "Подготовительные работы и вертикальная планировка",
        "Фундаментные работы",
        "Высокий цоколь",
        "Дренаж вокруг дома",
        "Гидроизоляция и утепление фундамента/цоколя",
        "Обратная отсыпка грунта",
        "Устройство перекрытия цоколя",
        "Кладка наружных и внутренних несущих стен — 1 этаж",
        "Устройство перемычек — 1 этаж",
        "Устройство перекрытия — 1 этаж",
        "Кладка наружных и внутренних несущих стен — 2 этаж",
        "Устройство перемычек — 2 этаж",
        "Устройство перекрытия — 2 этаж",
        "Устройство внутренних перегородок — этажи 1–2",
        "Устройство верхнего армопояса и крепление мауэрлата",
        "Утепление фасадных стен",
        "Кровельные работы",
        "Оконные и дверные блоки",
        "Наружная фасадная отделка",
    ]


def test_locked_group_sort_repairs_legacy_12_before_11_pair() -> None:
    from app.services.ktp_estimate_service import _sort_stage_groups

    groups = [
        SimpleNamespace(id="10", template_stage_number="2.7.10", sort_order=7000, title="10"),
        SimpleNamespace(id="12", template_stage_number="2.7.12", sort_order=8000, title="12"),
        SimpleNamespace(id="11", template_stage_number="2.7.11", sort_order=9000, title="11"),
        SimpleNamespace(id="13", template_stage_number="2.7.13", sort_order=10000, title="13"),
    ]

    ordered = _sort_stage_groups(groups, sequence_locked=True)

    assert [group.template_stage_number for group in ordered] == [
        "2.7.10",
        "2.7.11",
        "2.7.12",
        "2.7.13",
    ]


@pytest.mark.parametrize(
    "params,expected",
    [
        (BuildingParams(2, True, False), 19),
        (BuildingParams(2, False, False), 17),
        (BuildingParams(2, True, True), 18),
        (BuildingParams(1, False, False), 14),
    ],
)
def test_locked_sequence_count_formula(params: BuildingParams, expected: int) -> None:
    assert expected_locked_stage_instance_count(params) == expected
    assert len(build_stage_instances(_variant(), params)) == expected


def test_legacy_floor_schema_v2_is_unchanged() -> None:
    stages = build_stage_instances(
        _legacy_variant(),
        BuildingParams(3, True, True),
    )
    assert len(stages) == 25
    assert any(
        stage["template_stage_number"] == "2.7.9" and stage["floor_number"] == 0
        for stage in stages
    )
    assert any(
        stage["template_stage_number"] == "2.7.11" and stage["floor_number"] == 0
        for stage in stages
    )


def test_locked_sequence_mansard_keeps_walls_and_lintels_but_omits_slab() -> None:
    stages = _stages(mansard=True)
    mansard = [stage for stage in stages if stage.get("floor_number") == 2]
    assert {stage["template_stage_number"] for stage in mansard} == {"2.7.8", "2.7.9"}


def test_locked_sequence_has_one_deterministic_aggregate_partitions() -> None:
    first = _stages()
    second = _stages()
    aggregate = next(stage for stage in first if stage["template_stage_number"] == "2.7.11")
    repeated = next(stage for stage in second if stage["template_stage_number"] == "2.7.11")
    assert aggregate["stage_instance_id"].endswith(
        ":aggregate:floors:1-2:internal_partitions"
    )
    assert aggregate["stage_instance_id"] == repeated["stage_instance_id"]
    assert aggregate["aggregate_floor_numbers"] == [1, 2]
    assert aggregate["floor_kind"] == "aggregate"


def test_each_template_has_one_anchor_and_floor_one_anchors_repeated_templates() -> None:
    stages = _stages(floors=3)
    templates = {stage["template_stage_number"] for stage in stages}
    for template in templates:
        group = [stage for stage in stages if stage["template_stage_number"] == template]
        anchors = [stage for stage in group if stage["classification_candidate"]]
        assert len(anchors) == 1
        assert all(stage["projection_target"] for stage in group)
        if template in {"2.7.8", "2.7.9", "2.7.10"}:
            assert anchors[0]["floor_number"] == 1


def test_locked_classifier_ignores_out_of_range_floor_text(monkeypatch) -> None:
    import app.services.stage_classifier as module

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("legacy floor filter must not run")

    monkeypatch.setattr(module, "_filter_stages_by_floor_reference", fail_if_called)
    match = StageClassifier(get_sequential_scoring_policy()).classify_row_to_stage(
        "Кладка стен 5 этажа",
        "work",
        _stages(),
        estimate_profile_id="residential_construction",
    )
    assert match.stage is not None
    assert match.stage["template_stage_number"] == "2.7.8"
    assert match.stage["floor_number"] == 1


def test_wall_quantity_projects_from_anchor_to_all_floors() -> None:
    stages = _stages(floors=3)
    anchor = next(
        stage
        for stage in stages
        if stage["template_stage_number"] == "2.7.8" and stage["floor_number"] == 1
    )
    row = SimpleNamespace(
        quantity=12.0,
        unit="м3",
        work_name="Кладка стен",
        raw_data={
            "row_role": "work",
            "work_type_applicable": True,
            "operation_code": "brick_masonry",
            "template_stage_number": "2.7.8",
            "stage_instance_id": anchor["stage_instance_id"],
            "floor_number": 1,
            "floor_kind": "standard",
            "floor_label": "1 этаж",
            "floor_component": "walls",
            "source_row_key": "00000000-0000-0000-0000-000000000001",
            "work_scope_key": "scope:walls",
            "applicability_hash": "hash",
            "applicability_hash_version": 2,
            "resolution_status": "resolved",
            "calculation_blocked": False,
        },
    )
    enrich_quantity_projections([row], variant=_variant(), stage_instances=stages)
    projections = row.raw_data["ktp_quantity_projections"]
    assert [projection["floor_number"] for projection in projections] == [1, 2, 3]
    assert [projection["quantity"] for projection in projections] == [12.0, 12.0, 12.0]


def test_partition_projection_is_single_aggregate_target() -> None:
    stages = _stages()
    aggregate = next(stage for stage in stages if stage["template_stage_number"] == "2.7.11")
    row = SimpleNamespace(
        quantity=24.0,
        unit="м2",
        work_name="Перегородки",
        raw_data={
            "row_role": "work",
            "work_type_applicable": True,
            "operation_code": "brick_masonry",
            "template_stage_number": "2.7.11",
            "stage_instance_id": aggregate["stage_instance_id"],
            "floor_number": None,
            "floor_kind": "aggregate",
            "floor_label": "Этажи 1–2",
            "floor_component": "partitions",
            "source_row_key": "00000000-0000-0000-0000-000000000002",
            "work_scope_key": "scope:partitions",
            "applicability_hash": "hash",
            "applicability_hash_version": 2,
            "resolution_status": "resolved",
            "calculation_blocked": False,
        },
    )
    enrich_quantity_projections([row], variant=_variant(), stage_instances=stages)
    assert row.raw_data["quantity_projection_count"] == 1
    projection = row.raw_data["ktp_quantity_projections"][0]
    assert projection["quantity"] == 24.0
    assert projection["target_aggregation_mode"] == "aggregate_floors"
    assert projection["target_aggregate_floor_numbers"] == [1, 2]


def test_locked_dependency_chain_skips_empty_and_fallback_groups() -> None:
    accepted = SimpleNamespace(review_status="accepted", gpr_included=True)
    groups = [
        SimpleNamespace(id="a", title="A", sort_order=1000, items=[accepted]),
        SimpleNamespace(id="empty", title="Empty", sort_order=2000, items=[]),
        SimpleNamespace(id="b", title="B", sort_order=3000, items=[accepted]),
        SimpleNamespace(id="fallback", title="Прочие позиции сметы", sort_order=4000, items=[accepted]),
        SimpleNamespace(id="c", title="C", sort_order=5000, items=[accepted]),
    ]
    report = build_locked_sequence_dependencies(groups)
    assert report.edges == (("b", "a"), ("c", "b"))
    assert report.milestone is None


def test_sequence_policy_uses_schema_presence_not_dictionary_version() -> None:
    locked = sequence_policy_from_snapshot({"variant": _variant()})
    editable = sequence_policy_from_snapshot({"variant": {"number": "2.7"}})
    assert locked.locked is True
    assert locked.source == "taxonomy_wbs_sequence_schema"
    assert editable.locked is False


def test_taxonomy_compatibility_accepts_v65_patch_line() -> None:
    from app.services.taxonomy_compatibility_service import batch_uses_legacy_taxonomy

    for version in (
        "construction_work_dictionary_v6_5_0@1.9.0",
        "construction_work_dictionary_v6_5_1@1.9.1",
        "construction_work_dictionary_v6_5_9@1.9.9",
    ):
        batch = SimpleNamespace(
            project_variant_id="residential_construction_kirpichnye_doma",
            taxonomy_resolution_mode="persisted_snapshot",
            taxonomy_snapshot={"source_dictionary_version": version},
        )
        assert batch_uses_legacy_taxonomy(batch, []) is False


def test_invalid_locked_schema_never_falls_back() -> None:
    variant = _variant()
    variant["wbs_sequence_schema"]["mode"] = "editable"
    with pytest.raises(FloorStructureContractError) as exc:
        build_stage_instances(variant, BuildingParams(2, True, False))
    assert exc.value.code == "invalid_wbs_sequence_mode"


def test_locked_materialization_keeps_empty_taxonomy_groups() -> None:
    from app.models import KtpEstimateSession
    from app.services.ktp_estimate_service import GROUPING_MODE_STAGE_AWARE, _materialize_wbs

    raw_groups = [
        {
            "title": stage["title"],
            "sort_order": stage["sort_order"],
            "section_key": f"stage:{stage['stage_instance_id']}",
            "stage_instance_id": stage["stage_instance_id"],
            "template_stage_number": stage["template_stage_number"],
            "stage_number": stage["number"],
            "canonical_stage_id": stage["canonical_stage_id"],
            "floor_number": stage["floor_number"],
            "floor_kind": stage["floor_kind"],
            "floor_label": stage["floor_label"],
            "floor_component": stage["floor_component"],
            "component_role": stage["component_role"],
            "sequence_mode": "locked",
            "items": [],
        }
        for stage in _stages()
    ]
    session = KtpEstimateSession(
        id="00000000-0000-0000-0000-000000000010",
        project_id="00000000-0000-0000-0000-000000000011",
        estimate_batch_id="00000000-0000-0000-0000-000000000012",
    )
    groups, items, warnings = _materialize_wbs(
        session,
        raw_groups,
        {},
        grouping_mode=GROUPING_MODE_STAGE_AWARE,
    )
    assert len(groups) == 19
    assert items == []
    assert warnings == []
    assert [float(group.sort_order) for group in groups] == list(range(1000, 20000, 1000))
    assert [group.wbs_code for group in groups] == [
        group.template_stage_number for group in groups
    ]
    assert any(group.stage_number == "2.7.F1.10" for group in groups)
    assert next(group for group in groups if group.template_stage_number == "2.7.11").floor_kind == "aggregate"


def test_visible_locked_groups_follow_current_building_params_and_options() -> None:
    from app.services.ktp_estimate_service import _filter_visible_locked_groups

    current_batch = SimpleNamespace(
        id="batch-current",
        project_variant_id="residential_construction_kirpichnye_doma",
        building_params={
            "floors_count": 1,
            "has_basement": False,
            "has_mansard": False,
        },
        project_structure_options={
            "residential_construction.fundamentnye_raboty": "usp",
            "residential_construction.ustroystvo_peremychek_nad_proemami_kladki_etazha": "metal",
            "residential_construction.ustroystvo_perekrytiy_etazha": "monolithic_rc",
            "residential_construction.ustroystvo_vnutrennih_peregorodok_etazha": "block",
            "residential_construction.naruzhnaya_fasadnaya_otdelka": "no_finish",
        },
        taxonomy_snapshot=build_immutable_taxonomy_snapshot(
            project_variant_id="residential_construction_kirpichnye_doma",
        ).to_json(),
    )
    stale_groups = [
        SimpleNamespace(
            stage_instance_id=stage["stage_instance_id"],
            template_stage_number=stage["template_stage_number"],
        )
        for stage in _stages(floors=1, basement=True, mansard=False)
    ]

    visible = _filter_visible_locked_groups(
        stale_groups,
        batch=current_batch,
        sequence_locked=True,
    )
    visible_templates = [group.template_stage_number for group in visible]

    assert "2.7.3" not in visible_templates
    assert "2.7.7" not in visible_templates
    assert "2.7.16" not in visible_templates
    assert "2.7.15" in visible_templates


@pytest.mark.asyncio
async def test_locked_propose_sequence_is_idempotent_and_does_not_call_ai() -> None:
    import app.services.ktp_estimate_service as service

    session = SimpleNamespace(status="gpr_pending", updated_at=None)
    policy = SequencePolicy("locked", {}, "taxonomy_wbs_sequence_schema")
    db = AsyncMock()
    payload = {"groups": [], "sequence_locked": True}
    with (
        patch.object(service, "get_session_by_id", AsyncMock(return_value=session)),
        patch.object(service, "load_sequence_policy_for_session", AsyncMock(return_value=policy)),
        patch.object(service, "get_wbs", AsyncMock(return_value=payload)),
        patch("app.services.ktp_gpr_service._ai_order_groups", AsyncMock()) as ai_order,
    ):
        result = await service.propose_group_sequence(db, "project", "session")
    assert result == payload
    assert session.status == "gpr_sequence_review"
    ai_order.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_locked_dependency_resolver_does_not_call_ai() -> None:
    from app.services.ktp_gpr_service import _resolve_group_dependencies

    accepted = SimpleNamespace(review_status="accepted", gpr_included=True)
    groups = [
        SimpleNamespace(id="a", title="A", sort_order=1000, items=[accepted]),
        SimpleNamespace(id="b", title="B", sort_order=2000, items=[accepted]),
    ]
    policy = SequencePolicy("locked", {}, "taxonomy_wbs_sequence_schema")
    with patch("app.services.ktp_gpr_service.create_chat_completion", AsyncMock()) as ai_call:
        edges = await _resolve_group_dependencies(groups, [], sequence_policy=policy)
    assert edges == [("b", "a")]
    ai_call.assert_not_awaited()


def test_wbs_api_exposes_locked_policy_and_floor_kind() -> None:
    from app.api.routes.ktp_estimate import WbsOut
    from app.models import KtpEstimateSession, KtpWbsGroup

    session = KtpEstimateSession(
        id="00000000-0000-0000-0000-000000000020",
        project_id="00000000-0000-0000-0000-000000000021",
        estimate_batch_id="00000000-0000-0000-0000-000000000022",
        status="stage1_review",
    )
    group = KtpWbsGroup(
        id="00000000-0000-0000-0000-000000000023",
        session_id=session.id,
        project_id=session.project_id,
        title="Перегородки",
        sort_order=1000,
        status="draft",
        floor_kind="aggregate",
    )
    result = WbsOut.of(
        {
            "session": session,
            "groups": [group],
            "group_dependencies": [],
            "session_subtypes": [],
            "sequence_mode": "locked",
            "sequence_locked": True,
            "sequence_source": "taxonomy_wbs_sequence_schema",
        }
    )
    assert result.sequence_locked is True
    assert result.sequence_mode == "locked"
    assert result.groups[0].floor_kind == "aggregate"


@pytest.mark.asyncio
async def test_locked_group_crud_raises_stable_conflict() -> None:
    import app.services.ktp_estimate_service as service
    from app.services.ktp_errors import SequenceLockedByTaxonomy

    session = SimpleNamespace(id="session", estimate_batch_id="batch")
    group = SimpleNamespace(
        id="group",
        session_id="session",
        title="Фундамент",
        sort_order=1000,
        stage_instance_id="stage:global:foundation",
        items=[],
    )
    policy = SequencePolicy("locked", {}, "taxonomy_wbs_sequence_schema")
    db = AsyncMock()
    with (
        patch.object(service, "get_session_by_id", AsyncMock(return_value=session)),
        patch.object(service, "load_sequence_policy_for_session", AsyncMock(return_value=policy)),
    ):
        with pytest.raises(SequenceLockedByTaxonomy) as create_error:
            await service.create_group(db, "project", "session", {"title": "Новая"})
    assert create_error.value.code == "sequence_is_locked_by_taxonomy"

    with (
        patch.object(service, "_get_group", AsyncMock(return_value=group)),
        patch.object(service, "get_session_by_id", AsyncMock(return_value=session)),
        patch.object(service, "load_sequence_policy_for_session", AsyncMock(return_value=policy)),
    ):
        with pytest.raises(SequenceLockedByTaxonomy):
            await service.update_group(db, "project", "group", {"title": "Другое"})
        with pytest.raises(SequenceLockedByTaxonomy):
            await service.delete_group(db, "project", "group")
