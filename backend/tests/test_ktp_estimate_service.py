from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def make_session(sid: str = "sess-1", project_id: str = "p1"):
    s = MagicMock()
    s.id = sid
    s.project_id = project_id
    return s


def make_est(
    eid: str,
    work_name: str,
    unit: str = "м2",
    quantity: float = 10.0,
    section: str | None = None,
    row_order: int = 0,
):
    e = MagicMock()
    e.id = eid
    e.work_name = work_name
    e.unit = unit
    e.quantity = quantity
    e.section = section
    e.row_order = row_order
    e.total_price = None
    e.raw_data = {}
    e.work_section_code = None
    e.work_section_name = None
    e.work_subtype_code = None
    e.work_subtype_name = None
    e.classification_confidence = None
    e.classification_needs_review = False
    e.classification_candidates = None
    e.classification_source = None
    e.operator_review_required = False
    e.manual_override = False
    e.work_stage_number = None
    e.work_stage_title = None
    e.stage_title = None
    e.dictionary_version = None
    e.taxonomy_dictionary_version = None
    e.project_variant_id = None
    e.project_variant_number = None
    e.stage_instance_id = None
    e.canonical_stage_id = None
    e.needs_review = False
    e.review_reason = None
    e.stage_match_score_json = None
    e.section_id = None
    e.subtype_id = None
    return e


def make_batch(
    *,
    estimate_type_id: str = "residential_construction",
    project_variant_id: str = "residential_construction_doma_iz_peno_ili_gazoblokov",
):
    return SimpleNamespace(
        id="batch-1",
        estimate_type_id=estimate_type_id,
        estimate_type_title=None,
        estimate_type_number=None,
        project_variant_id=project_variant_id,
        project_variant_title=None,
        project_variant_number=None,
        taxonomy_snapshot=None,
        building_params=None,
        raw_data={},
    )


def _make_diag() -> dict:
    return {
        "chunk_errors": [],
        "raw_samples": [],
        "coverage": [],
        "wt_code_conflicts": [],
        "work_section_code_conflicts": [],
        "invalid_work_section_codes": [],
        "gap_fill_trimmed": [],
        "repeated_sections": [],
        "unassigned_ai_items": [],
    }


def test_gpr_blocker_is_computed_from_review_flags_and_confirmation():
    from app.services.ktp_estimate_service import gpr_blocker

    item = MagicMock()
    item.operator_review_required = True
    item.work_type_needs_review = False
    item.gpr_confirmed = False
    assert gpr_blocker(item) is True

    item.gpr_confirmed = True
    assert gpr_blocker(item) is False


# ── инвариант покрытия ───────────────────────────────────────────────────────

def test_materialize_wbs_missing_row_goes_to_fallback_group():
    from app.services.ktp_estimate_service import (
        FALLBACK_GROUP_TITLE,
        _materialize_wbs,
    )

    e1 = make_est("e1", "Кладка стен")
    e2 = make_est("e2", "Штукатурка")
    row_keys = {"R001": e1, "R002": e2}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"}
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)

    fallback = [g for g in groups if g.title == FALLBACK_GROUP_TITLE]
    assert len(fallback) == 1
    covered = {it.estimate_id for it in items if it.origin == "from_estimate"}
    assert covered == {"e1", "e2"}
    assert any("не распределены" in w for w in warnings)


def test_materialize_wbs_duplicate_estimate_kept_once_with_warning():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "Кладка стен")
    row_keys = {"R001": e1}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"},
                {"name": "Кладка (дубль)", "origin": "from_estimate", "row_key": "R001"},
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)

    from_estimate = [it for it in items if it.estimate_id == "e1"]
    assert len(from_estimate) == 1
    assert any("продублирована" in w for w in warnings)


def test_materialize_wbs_unknown_row_key_is_rejected_not_ai_added():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "Кладка стен")
    row_keys = {"R001": e1}
    diagnostics = {}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"},
                {"name": "Призрак", "origin": "from_estimate", "row_key": "R999"},
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(
        make_session(), raw_groups, row_keys, diagnostics=diagnostics
    )

    assert not [it for it in items if it.name == "Призрак"]
    assert diagnostics["invalid_estimate_row_keys"][0]["row_key"] == "R999"
    assert any("AI-item не создан" in w for w in warnings)


def test_materialize_wbs_ai_added_is_pending():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "Кладка стен")
    row_keys = {"R001": e1}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"},
                {
                    "name": "Вывоз мусора",
                    "origin": "ai_added",
                    "ai_reason": "обязательный этап",
                },
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)

    added = [it for it in items if it.origin == "ai_added"][0]
    assert added.review_status == "pending"
    assert added.ai_reason == "обязательный этап"
    # все позиции сметы покрыты — лишних предупреждений нет
    assert not any("не распределены" in w for w in warnings)


def test_stage_aware_groups_use_json_work_stage_order():
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    e1 = make_est("e1", "Монтаж металлочерепицы", row_order=20)
    e1.work_stage_number = "2.6.14"
    e1.work_stage_title = "Кровельные работы"
    e1.section_id = "roofing"
    e1.subtype_id = "pitched_roof_covering"
    e1.work_subtype_code = "roofing/pitched_roof_covering"
    e1.raw_data["taxonomy_legacy"] = False
    e2 = make_est("e2", "Кладка стен", row_order=10)
    e2.work_stage_number = "2.6.6"
    e2.work_stage_title = "Кладка стен 1 этажа"
    e2.section_id = "load_bearing_walls"
    e2.subtype_id = "block_walls"
    e2.work_subtype_code = "load_bearing_walls/block_walls"
    e2.raw_data["taxonomy_legacy"] = False
    batch = make_batch()
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups(
        [e1, e2],
        {"e1": "R001", "e2": "R002"},
        batch,
        diagnostics,
    )

    stage_numbers = [g["work_stage_number"] for g in groups]
    assert "2.6.2" in stage_numbers
    assert "2.6.3" in stage_numbers
    assert stage_numbers.index("2.6.6") < stage_numbers.index("2.6.14")
    by_stage = {g["work_stage_number"]: g for g in groups}
    assert by_stage["2.6.6"]["title"].startswith("2.6.6.")
    assert by_stage["2.6.6"]["items"] == [{"name": "Кладка стен", "origin": "from_estimate", "row_key": "R002"}]
    assert by_stage["2.6.14"]["items"] == [{"name": "Монтаж металлочерепицы", "origin": "from_estimate", "row_key": "R001"}]
    assert by_stage["2.6.2"]["items"] == []
    assert diagnostics["stage_grouping"]["mode"] == "stage_aware"


def test_stage_aware_groups_put_rows_without_stage_to_fallback():
    from app.services.ktp_estimate_service import STAGE_AWARE_FALLBACK_TITLE, _build_stage_aware_groups

    e1 = make_est("e1", "Нераспознанная работа")
    e1.raw_data["taxonomy_legacy"] = False
    batch = make_batch()
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups([e1], {"e1": "R001"}, batch, diagnostics)

    assert groups[-1]["title"] == STAGE_AWARE_FALLBACK_TITLE
    assert groups[-1]["items"][0]["row_key"] == "R001"
    assert diagnostics["stage_grouping"]["fallback_rows"][0]["reason"] == "missing_work_stage_number"


def test_stage_aware_groups_add_catalog_recommendations_by_template_stage(monkeypatch, tmp_path):
    import app.services.ktp_estimate_service as svc
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text("{}", encoding="utf-8")
    catalog = SimpleNamespace(
        sources=[
            SimpleNamespace(
                id="src-brick",
                is_active=True,
                metadata_json={"variant_id": "residential_construction_kirpichnye_doma"},
            )
        ],
        items=[
            SimpleNamespace(
                id="rate-1",
                source_id="src-brick",
                source_row=1,
                name="Подача кирпича и раствора",
                is_active=True,
                row_role="work",
                source_rate_id="labor:8:66",
                source_payload={"stage_number": "2.7.8", "selected_target_code": "brick_material_lifting"},
                applicability_json={"template_stage_numbers": ["2.7.8"]},
            )
        ],
        mappings=[
            SimpleNamespace(
                id="map-1",
                rate_item_id="rate-1",
                is_active=True,
                is_primary=True,
                priority=100,
                confidence=0.99,
                operation_code="brick_material_lifting",
                diagnostics={"preferred_stage_number": "2.7.8"},
            )
        ],
    )
    monkeypatch.setattr(svc, "resolve_config_path", lambda _path: catalog_file)
    monkeypatch.setattr(svc, "_load_work_rate_catalog_cached", lambda _path: catalog)

    e1 = make_est("e1", "Кладка стен", row_order=1)
    e1.work_stage_number = "2.7.F1.10"
    e1.template_stage_number = "2.7.8"
    e1.work_stage_title = "Кладка наружных и внутренних несущих стен из кирпича"
    e1.work_subtype_code = "load_bearing_walls/brick_walls"
    e1.section_id = "load_bearing_walls"
    e1.subtype_id = "brick_walls"
    e1.project_variant_id = "residential_construction_kirpichnye_doma"
    e1.raw_data["taxonomy_legacy"] = True
    batch = make_batch(project_variant_id="residential_construction_kirpichnye_doma")
    batch.work_rate_catalog_version = "1.2"
    batch.building_params = {"floors_count": 1}
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups([e1], {"e1": "R001"}, batch, diagnostics)

    target = next(g for g in groups if g.get("template_stage_number") == "2.7.8")
    added = [it for it in target["items"] if it["origin"] == "ai_added"]
    assert added == [
        {
            "name": "Подача кирпича и раствора",
            "origin": "ai_added",
            "row_key": None,
            "review_status": "pending",
            "ai_reason": "Рекомендовано из загруженного справочника работ",
            "recommendation_source": "work_rate_catalog",
            "source_rate_id": "labor:8:66",
            "rate_item_id": "rate-1",
            "rate_mapping_id": "map-1",
            "operation_code": "brick_material_lifting",
            "semantic_stage_option_id": None,
            "stage_option_source": "work_rate_catalog",
        }
    ]
    assert diagnostics["catalog_recommendations"][0]["preferred_stage_number"] == "2.7.8"


def test_stage_confidence_percent_uses_score_and_delta_caps():
    from app.services.ktp_estimate_service import _stage_confidence_percent

    assert _stage_confidence_percent({"winner": {"score": 7}, "delta_top_1_top_2": 3}) == 50
    assert _stage_confidence_percent({"winner": {"score": 14}, "delta_top_1_top_2": 1.5}) == 50
    assert _stage_confidence_percent({"winner": {"score": 20}, "delta_top_1_top_2": 9}) == 100
    assert _stage_confidence_percent({}) is None


def test_stage_aware_groups_keep_stage_review_rows_in_valid_stage():
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    e1 = make_est("e1", "Утепление кровли", row_order=1)
    e1.work_stage_number = "2.7.4"
    e1.work_stage_title = "Гидроизоляция и утепление фундамента/цоколя"
    e1.section_id = "insulation"
    e1.subtype_id = "roof_attic_insulation"
    e1.work_subtype_code = "insulation/roof_attic_insulation"
    e1.stage_match_score_json = {
        "needs_review": False,
        "reason": None,
        "candidate_scores": [
            {
                "match_type": "stage_option_match",
                "matched_terms": {
                    "stage_title": ["утепление"],
                    "stage_option": ["утепление/защита"],
                    "canonical_stage": ["утепление"],
                },
            }
        ],
    }
    e2 = make_est("e2", "Гидроизоляция фундамента", row_order=2)
    e2.work_stage_number = "2.7.4"
    e2.work_stage_title = "Гидроизоляция и утепление фундамента/цоколя"
    e2.needs_review = True
    e2.review_reason = "work_type_candidates_ambiguous"
    e2.section_id = "waterproofing"
    e2.subtype_id = "underground_structure_waterproofing"
    e2.work_subtype_code = "waterproofing/underground_structure_waterproofing"
    e2.stage_match_score_json = {
        "needs_review": False,
        "reason": None,
    }
    batch = MagicMock()
    batch.estimate_type_id = "residential_construction"
    batch.project_variant_id = "residential_construction_kirpichnye_doma"
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups(
        [e1, e2],
        {"e1": "R001", "e2": "R002"},
        batch,
        diagnostics,
    )

    by_stage = {g["work_stage_number"]: g for g in groups if g.get("work_stage_number")}
    assert by_stage["2.7.4"]["items"] == [
        {"name": "Утепление кровли", "origin": "from_estimate", "row_key": "R001"},
        {"name": "Гидроизоляция фундамента", "origin": "from_estimate", "row_key": "R002"},
    ]
    assert not diagnostics["stage_grouping"]["fallback_rows"]
    assert diagnostics["stage_grouping"]["review_rows"][0]["row_key"] == "R001"
    assert diagnostics["stage_grouping"]["review_rows"][0]["review_reason"] == "stage_weak_partial_text_match"


def test_stage_aware_groups_keep_unresolved_work_type_rows_in_valid_stage():
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    e1 = make_est("e1", "Непонятная работа", row_order=1)
    e1.work_stage_number = "2.7.2"
    e1.work_stage_title = "Фундаментные работы"
    e1.work_subtype_code = "unknown/needs_review"
    e1.classification_needs_review = True
    e2 = make_est("e2", "Гидроизоляция фундамента", row_order=2)
    e2.work_stage_number = "2.7.4"
    e2.work_stage_title = "Гидроизоляция и утепление фундамента/цоколя"
    e2.section_id = "waterproofing"
    e2.subtype_id = "underground_structure_waterproofing"
    e2.work_subtype_code = "waterproofing/underground_structure_waterproofing"
    batch = MagicMock()
    batch.estimate_type_id = "residential_construction"
    batch.project_variant_id = "residential_construction_kirpichnye_doma"
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups(
        [e1, e2],
        {"e1": "R001", "e2": "R002"},
        batch,
        diagnostics,
    )

    by_stage = {g["work_stage_number"]: g for g in groups if g.get("work_stage_number")}
    assert by_stage["2.7.2"]["items"] == [{"name": "Непонятная работа", "origin": "from_estimate", "row_key": "R001"}]
    assert by_stage["2.7.4"]["items"] == [{"name": "Гидроизоляция фундамента", "origin": "from_estimate", "row_key": "R002"}]
    assert not diagnostics["stage_grouping"]["fallback_rows"]
    assert diagnostics["stage_grouping"]["review_rows"][0]["row_key"] == "R001"
    assert diagnostics["stage_grouping"]["review_rows"][0]["work_type_review_reason"] == "legacy_work_type_mapping_ambiguous"


def test_stage_aware_groups_put_invalid_stage_to_fallback():
    from app.services.ktp_estimate_service import STAGE_AWARE_FALLBACK_TITLE, _build_stage_aware_groups

    e1 = make_est("e1", "Работа с чужим этапом", row_order=1)
    e1.work_stage_number = "9.9.9"
    e1.work_subtype_code = "foundation/foundation_works"
    e1.raw_data["taxonomy_legacy"] = False
    batch = make_batch()
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups([e1], {"e1": "R001"}, batch, diagnostics)

    assert groups[-1]["title"] == STAGE_AWARE_FALLBACK_TITLE
    assert groups[-1]["items"] == [{"name": "Работа с чужим этапом", "origin": "from_estimate", "row_key": "R001"}]
    assert diagnostics["stage_grouping"]["invalid_stage_rows"][0]["work_stage_number"] == "9.9.9"


def test_stage_aware_groups_accept_work_subtype_code_without_split_ids():
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    e1 = make_est("e1", "Укладка гильзы под ввод коммуникаций", row_order=1)
    e1.work_stage_number = "2.7.5"
    e1.work_stage_title = "Устройство перекрытий цоколя"
    e1.work_subtype_code = "floor_slabs/timber_floor"
    batch = MagicMock()
    batch.estimate_type_id = "residential_construction"
    batch.project_variant_id = "residential_construction_kirpichnye_doma"
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups([e1], {"e1": "R001"}, batch, diagnostics)

    by_stage = {g["work_stage_number"]: g for g in groups if g.get("work_stage_number")}
    assert by_stage["2.7.5"]["items"] == [
        {"name": "Укладка гильзы под ввод коммуникаций", "origin": "from_estimate", "row_key": "R001"}
    ]
    assert not diagnostics["stage_grouping"]["fallback_rows"]


def test_stage_aware_groups_keeps_known_work_type_even_if_review_flagged():
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    e1 = make_est("e1", "Утепление фундамента", row_order=1)
    e1.work_stage_number = "2.7.4"
    e1.work_stage_title = "Гидроизоляция и утепление фундамента/цоколя"
    e1.work_subtype_code = "foundation/foundation_protection_insulation"
    e1.classification_needs_review = True
    e1.operator_review_required = True
    batch = MagicMock()
    batch.estimate_type_id = "residential_construction"
    batch.project_variant_id = "residential_construction_kirpichnye_doma"
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups([e1], {"e1": "R001"}, batch, diagnostics)

    by_stage = {g["work_stage_number"]: g for g in groups if g.get("work_stage_number")}
    assert by_stage["2.7.4"]["items"] == [
        {"name": "Утепление фундамента", "origin": "from_estimate", "row_key": "R001"}
    ]
    assert not diagnostics["stage_grouping"]["fallback_rows"]


def test_stage_aware_groups_keeps_high_confidence_partial_stage_match():
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    e1 = make_est("e1", "Кирпичная кладка вентканалов", row_order=1)
    e1.work_stage_number = "2.7.6"
    e1.work_stage_title = "Кладка наружных и внутренних несущих стен из кирпича 1 этаж"
    e1.work_subtype_code = "load_bearing_walls/vent_shafts_masonry"
    e1.stage_match_score_json = {
        "needs_review": True,
        "reason": "stage_weak_partial_text_match",
        "winner": {"score": 18},
        "candidate_scores": [
            {
                "match_type": "near_stage_title_match",
                "matched_terms": {
                    "stage_title": ["кладка", "стен", "кирпича"],
                    "canonical_stage": ["кладка", "стен", "кирпича"],
                },
            }
        ],
    }
    batch = MagicMock()
    batch.estimate_type_id = "residential_construction"
    batch.project_variant_id = "residential_construction_kirpichnye_doma"
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups([e1], {"e1": "R001"}, batch, diagnostics)

    by_stage = {g["work_stage_number"]: g for g in groups if g.get("work_stage_number")}
    assert by_stage["2.7.6"]["items"] == [
        {"name": "Кирпичная кладка вентканалов", "origin": "from_estimate", "row_key": "R001"}
    ]
    assert not diagnostics["stage_grouping"]["fallback_rows"]


def test_stage_aware_groups_keeps_ambiguous_primary_work_type_winner():
    from app.services.ktp_estimate_service import _build_stage_aware_groups

    e1 = make_est("e1", "Монтаж перемычек", row_order=1)
    e1.work_stage_number = "2.7.8"
    e1.work_stage_title = "Устройство перемычек над проемами кладки 1 этажа"
    e1.work_subtype_code = "load_bearing_walls/arm_belts_lintels"
    e1.stage_match_score_json = {
        "needs_review": True,
        "reason": "stage_candidates_ambiguous",
        "winner": {"score": 12},
        "candidate_scores": [
            {
                "match_type": "near_stage_title_match",
                "matched_terms": {
                    "stage_title": ["перемычек"],
                    "primary_work_type": ["load_bearing_walls/arm_belts_lintels"],
                },
            }
        ],
    }
    batch = MagicMock()
    batch.estimate_type_id = "residential_construction"
    batch.project_variant_id = "residential_construction_kirpichnye_doma"
    diagnostics = _make_diag()

    groups = _build_stage_aware_groups([e1], {"e1": "R001"}, batch, diagnostics)

    by_stage = {g["work_stage_number"]: g for g in groups if g.get("work_stage_number")}
    assert by_stage["2.7.8"]["items"] == [
        {"name": "Монтаж перемычек", "origin": "from_estimate", "row_key": "R001"}
    ]
    assert not diagnostics["stage_grouping"]["fallback_rows"]


@pytest.mark.asyncio
async def test_run_stage1_preserve_estimate_structure_uses_estimate_sections():
    import app.services.ktp_estimate_service as svc

    e1 = make_est("e1", "Кладка стен", section="Раздел сметы", row_order=1)
    diagnostics = _make_diag()

    async def fake_clean_pass(python_groups, *_args, **_kwargs):
        for group in python_groups.values():
            group["cleaned_title"] = group["display_title"]
            group["cleaned_items"] = [
                {"name": est.work_name, "origin": "from_estimate", "row_key": row_key}
                for row_key, est in group["rows"]
            ]

    with (
        patch.object(svc, "_run_section_clean_pass", AsyncMock(side_effect=fake_clean_pass)),
        patch.object(svc, "_run_per_group_gap_fill", AsyncMock()),
        patch.object(svc, "_run_project_gap_fill", AsyncMock()),
    ):
        groups = await svc._run_stage1(
            [e1],
            {"R001": e1},
            [],
            "Жилое здание",
            None,
            diagnostics=diagnostics,
            preserve_estimate_structure=True,
        )

    assert groups[0]["title"] == "Раздел сметы"
    assert groups[0]["items"][0]["row_key"] == "R001"


# ── промпт ───────────────────────────────────────────────────────────────────

def test_build_stage1_prompt_contains_row_keys_and_gap_instruction():
    from app.services.ktp_estimate_service import _build_stage1_prompt

    rows = [("R001", make_est("e1", "Кладка стен"))]
    section_palette = [
        {
            "section_code": "load_bearing_walls",
            "section_name": "Несущие стены",
            "examples": [
                {
                    "work_subtype_code": "load_bearing_walls/block_walls",
                    "work_subtype_name": "Кладка из блоков",
                    "display_code": "3.2",
                }
            ],
            "is_primary": True,
        }
    ]

    with_gap = _build_stage1_prompt(rows, section_palette, "Жилое здание", gap_fill=True)
    assert "R001" in with_gap
    assert "Кладка стен" in with_gap
    assert "work_section_code" in with_gap
    assert "load_bearing_walls" in with_gap
    assert "ОТСУТСТВУЮТ" in with_gap

    no_gap = _build_stage1_prompt(rows, section_palette, "Жилое здание", gap_fill=False)
    assert "НЕ добавляй" in no_gap


def test_parse_stage1_response_extracts_groups():
    from app.services.ktp_estimate_service import _parse_stage1_response

    groups = _parse_stage1_response('{"groups": [{"title": "Г1", "items": []}]}')
    assert groups == [{"title": "Г1", "items": []}]


def test_parse_stage1_response_raises_without_groups():
    from app.services.ktp_estimate_service import _parse_stage1_response

    with pytest.raises(ValueError, match="без списка groups"):
        _parse_stage1_response('{"foo": 1}')


def test_parse_json_object_tolerates_trailing_commas():
    from app.services.openrouter_embeddings import parse_json_object

    # типовая ошибка gpt-4o-mini: запятая перед закрывающей скобкой
    result = parse_json_object('{"groups": [{"title": "Г1", "items": [],}],}')
    assert result == {"groups": [{"title": "Г1", "items": []}]}


def test_parse_json_object_strips_line_comments():
    from app.services.openrouter_embeddings import parse_json_object

    result = parse_json_object(
        '{\n  "groups": [\n    // inline comment\n    {"title": "Г1"}\n  ]\n}'
    )
    assert result == {"groups": [{"title": "Г1"}]}


def test_stage1_job_stale_detection_uses_started_at():
    from datetime import datetime, timedelta, timezone

    from app.services.ktp_estimate_service import _is_stale_stage1_job

    job = MagicMock()
    job.type = "ktp_estimate_stage1"
    job.status = "processing"
    job.started_at = datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)
    job.created_at = job.started_at - timedelta(minutes=1)

    assert _is_stale_stage1_job(
        job,
        now=job.started_at + timedelta(hours=3),
    )


def test_non_stage1_job_is_not_stale_for_ktp_recovery():
    from datetime import datetime, timedelta, timezone

    from app.services.ktp_estimate_service import _is_stale_stage1_job

    job = MagicMock()
    job.type = "estimate_upload"
    job.status = "processing"
    job.started_at = datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)
    job.created_at = job.started_at

    assert not _is_stale_stage1_job(
        job,
        now=job.started_at + timedelta(days=1),
    )


# ── section_key и python_groups ─────────────────────────────────────────────

def test_make_section_key_stable_and_versioned():
    from app.services.ktp_estimate_service import (
        _make_section_key,
        _normalize_section_title,
    )

    a = _make_section_key(1, _normalize_section_title("Кровля"))
    b = _make_section_key(1, _normalize_section_title("  кровля  "))
    assert a == b
    assert a.startswith("sec_0001_")


def test_build_python_groups_merges_repeated_sections():
    from app.services.ktp_estimate_service import _build_python_groups

    estimates = [
        make_est("e1", "Снятие отделки", section="Демонтаж", row_order=0),
        make_est("e2", "Монтаж стропил", section="Кровля", row_order=1),
        make_est("e3", "Вывоз мусора", section="демонтаж", row_order=2),
    ]
    diag = _make_diag()
    groups = _build_python_groups(estimates, {est.id: f"R{i}" for i, est in enumerate(estimates, start=1)}, diag)

    titles = sorted(g["display_title"] for g in groups.values())
    assert titles == ["Демонтаж", "Кровля"]

    demo = next(g for g in groups.values() if g["display_title"] == "Демонтаж")
    assert {row_key for row_key, _ in demo["rows"]} == {"R1", "R3"}
    assert demo["sort_order"] == 0
    assert len(diag["repeated_sections"]) == 1


def test_build_python_groups_collects_ungrouped():
    from app.services.ktp_estimate_service import _build_python_groups

    estimates = [
        make_est("e1", "A", section="Кровля", row_order=0),
        make_est("e2", "B", section=None, row_order=1),
        make_est("e3", "C", section="   ", row_order=2),
    ]
    diag = _make_diag()
    groups = _build_python_groups(estimates, {est.id: f"R{i}" for i, est in enumerate(estimates, start=1)}, diag)
    assert "__ungrouped__" in groups
    assert {row_key for row_key, _ in groups["__ungrouped__"]["rows"]} == {"R2", "R3"}


# ── валидаторы покрытия ─────────────────────────────────────────────────────

def test_validate_section_coverage_drops_unknown_and_duplicates_fills_missing():
    from app.services.ktp_estimate_service import _validate_section_coverage

    e1, e2, e3 = (
        make_est("e1", "Кладка"),
        make_est("e2", "Штукатурка"),
        make_est("e3", "Покраска"),
    )
    section_rows = [("R001", e1), ("R002", e2), ("R003", e3)]
    items = [
        {"row_key": "R001", "name": "Кладка стен"},
        {"row_key": "R001", "name": "Дубль"},   # duplicate
        {"row_key": "R999", "name": "Призрак"},  # unknown
        # R002, R003 — missing
    ]
    diag = _make_diag()
    cleaned = _validate_section_coverage(
        items=items,
        section_rows=section_rows,
        section_key="sec_0001_abc",
        chunk_label="sec_test",
        diagnostics=diag,
    )

    by_key = {it["row_key"]: it for it in cleaned}
    assert set(by_key.keys()) == {"R001", "R002", "R003"}
    assert by_key["R001"]["name"] == "Кладка стен"
    # missing восстановлены из Estimate.work_name
    assert by_key["R002"]["name"] == "Штукатурка"
    assert by_key["R003"]["name"] == "Покраска"

    cov = diag["coverage"][0]
    assert "R999" in cov["unknown"]
    assert "R001" in cov["duplicated"]
    assert set(cov["missing"]) == {"R002", "R003"}


def test_validate_ungrouped_coverage_routes_invalid_to_fallback():
    from app.services.ktp_estimate_service import _validate_ungrouped_coverage

    e1, e2, e3 = (
        make_est("e1", "A"),
        make_est("e2", "B"),
        make_est("e3", "C"),
    )
    orphan_rows = [("R1", e1), ("R2", e2), ("R3", e3)]
    assignments = [
        {"row_key": "R1", "assigned_section_key": "sec_0001_ok", "name": "A norm"},
        {"row_key": "R2", "assigned_section_key": "sec_bogus", "name": "B"},  # invalid
        # R3 — отсутствует
    ]
    diag = _make_diag()
    cleaned, fallback = _validate_ungrouped_coverage(
        assignments=assignments,
        orphan_rows=orphan_rows,
        valid_section_keys={"sec_0001_ok"},
        diagnostics=diag,
    )

    assert [c["row_key"] for c in cleaned] == ["R1"]
    fallback_keys = {row_key for row_key, _ in fallback}
    assert fallback_keys == {"R2", "R3"}
    cov = diag["coverage"][0]
    assert "R2" in cov["invalid_assignment"]
    assert "R3" in cov["missing"]


# ── валидаторы формата ─────────────────────────────────────────────────────

def test_validate_section_response_drops_invalid_items():
    from app.services.ktp_estimate_service import _validate_section_response

    out = _validate_section_response(
        {
            "cleaned_title": "  Кровля  ",
            "work_section_code": "roofing",
            "items": [
                {"row_key": "R007", "name": "Монтаж"},
                {"row_key": "  ", "name": "пусто"},
                {"name": "без row_key"},
                "not a dict",
            ],
        }
    )
    assert out["cleaned_title"] == "Кровля"
    assert out["work_section_code"] == "roofing"
    assert out["items"] == [{"row_key": "R007", "name": "Монтаж"}]


def test_validate_per_group_gap_fill_requires_reason():
    from app.services.ktp_estimate_service import _validate_per_group_gap_fill_response

    out = _validate_per_group_gap_fill_response(
        {
            "added_items": [
                {"name": "Снегозадержатели", "ai_reason": "защита"},
                {"name": "без причины"},
                {"name": "", "ai_reason": "нет имени"},
            ]
        }
    )
    assert out == [{"name": "Снегозадержатели", "ai_reason": "защита"}]


def test_validate_project_gap_fill_drops_records_without_reason_or_group_key():
    from app.services.ktp_estimate_service import _validate_project_gap_fill_response

    out = _validate_project_gap_fill_response(
        {
            "distributed": [
                {"group_key": "sec_0001_a", "name": "Снег.", "ai_reason": "защита"},
                {"group_key": "sec_0001_a", "name": "без причины"},
                {"name": "без group_key", "ai_reason": "x"},
            ],
            "unassigned": [
                {"name": "Пусконаладка", "ai_reason": "запрошено"},
                {"name": "без причины"},
            ],
        }
    )
    assert out["distributed"] == [
        {"group_key": "sec_0001_a", "name": "Снег.", "ai_reason": "защита"}
    ]
    assert out["unassigned"] == [{"name": "Пусконаладка", "ai_reason": "запрошено"}]


# ── canonical assembly ─────────────────────────────────────────────────────

def test_assemble_canonical_adds_fallback_for_global_missing():
    from app.services.ktp_estimate_service import (
        FALLBACK_DISPLAY_TITLE,
        _assemble_canonical_groups,
    )

    e1 = make_est("e1", "A")
    e2 = make_est("e2", "B")
    row_keys = {"R1": e1, "R2": e2}
    python_groups = {
        "sec_0001_a": {
            "section_key": "sec_0001_a",
            "display_title": "Кровля",
            "cleaned_title": "Кровля",
            "rows": [("R1", e1)],
            "sort_order": 0,
            "cleaned_items": [{"name": "A", "origin": "from_estimate", "row_key": "R1"}],
            "work_section_code": "roofing",
            "work_section_name": "Кровельные работы",
            "gap_items": [
                {
                    "name": "Снегозадержатели",
                    "origin": "ai_added",
                    "row_key": None,
                    "review_status": "pending",
                    "ai_reason": "защита",
                }
            ],
        }
    }
    diag = _make_diag()
    out = _assemble_canonical_groups(python_groups, row_keys, diag)
    titles = [g["title"] for g in out]
    assert titles == ["Кровля", FALLBACK_DISPLAY_TITLE]
    fallback = next(g for g in out if g["title"] == FALLBACK_DISPLAY_TITLE)
    assert fallback["items"][0]["row_key"] == "R2"
    cov_kinds = {c["kind"] for c in diag["coverage"]}
    assert "global" in cov_kinds


def test_assemble_canonical_includes_ai_added_with_required_fields():
    from app.services.ktp_estimate_service import _assemble_canonical_groups

    e1 = make_est("e1", "A")
    row_keys = {"R1": e1}
    python_groups = {
        "sec_0001_a": {
            "section_key": "sec_0001_a",
            "display_title": "Кровля",
            "cleaned_title": "Кровля",
            "rows": [("R1", e1)],
            "sort_order": 0,
            "cleaned_items": [{"name": "A", "origin": "from_estimate", "row_key": "R1"}],
            "work_section_code": "roofing",
            "work_section_name": "Кровельные работы",
            "gap_items": [
                {
                    "name": "Снегозадержатели",
                    "origin": "ai_added",
                    "row_key": None,
                    "review_status": "pending",
                    "ai_reason": "защита",
                }
            ],
        }
    }
    out = _assemble_canonical_groups(python_groups, row_keys, _make_diag())
    assert len(out) == 1
    items = out[0]["items"]
    ai_added = [it for it in items if it["origin"] == "ai_added"]
    assert len(ai_added) == 1
    assert ai_added[0]["row_key"] is None
    assert ai_added[0]["review_status"] == "pending"


def test_assemble_canonical_dedups_ai_added_against_estimate_and_across_groups():
    """ai_added, совпадающий с работой сметы или повторяющийся в другой группе,
    отбрасывается (баги: «Гидроизоляция фундамента» ×2, «Армирование» в двух
    группах, «Вывоз мусора» уже в смете)."""
    from app.services.ktp_estimate_service import _assemble_canonical_groups

    e_hydro = make_est("e1", "Гидроизоляция фундамента", row_order=1)
    e_other = make_est("e2", "Кладка цоколя", row_order=2)
    row_keys = {"R1": e_hydro, "R2": e_other}
    python_groups = {
        "sec_0001_a": {
            "section_key": "sec_0001_a",
            "display_title": "Фундамент",
            "cleaned_title": "Фундамент",
            "rows": [("R1", e_hydro)],
            "sort_order": 0,
            "work_section_code": "foundation",
            "work_section_name": "Фундаментные работы",
            "cleaned_items": [
                {"name": "Гидроизоляция фундамента", "origin": "from_estimate", "row_key": "R1"}
            ],
            "gap_items": [
                # уже есть в смете → drop
                {"name": "Гидроизоляция фундамента.", "origin": "ai_added",
                 "row_key": None, "review_status": "pending", "ai_reason": "x"},
                # новая, корректная → keep
                {"name": "Армирование фундамента", "origin": "ai_added",
                 "row_key": None, "review_status": "pending", "ai_reason": "x"},
            ],
        },
        "sec_0002_b": {
            "section_key": "sec_0002_b",
            "display_title": "Цоколь",
            "cleaned_title": "Цоколь",
            "rows": [("R2", e_other)],
            "sort_order": 1,
            "work_section_code": "load_bearing_walls",
            "work_section_name": "Несущие стены",
            "cleaned_items": [
                {"name": "Кладка цоколя", "origin": "from_estimate", "row_key": "R2"}
            ],
            "gap_items": [
                # дубль ai_added из первой группы → drop
                {"name": "Армирование фундамента", "origin": "ai_added",
                 "row_key": None, "review_status": "pending", "ai_reason": "x"},
            ],
        },
    }
    diag = _make_diag()
    out = _assemble_canonical_groups(python_groups, row_keys, diag)
    ai_names = [
        it["name"]
        for g in out
        for it in g["items"]
        if it["origin"] == "ai_added"
    ]
    assert ai_names == ["Армирование фундамента"]
    dups = diag["gap_fill_duplicates"]
    reasons = {d["reason"] for d in dups}
    assert reasons == {"exists_in_estimate", "duplicate_gap"}


def test_filter_card_questions_drops_concrete_grade():
    from app.services.ktp_estimate_service import _filter_card_questions

    questions = [
        {"key": "concrete_grade", "label": "Какой класс бетона предусмотрен?"},
        {"key": "q1", "label": "Марка бетона фундамента?"},
        {"key": "q2", "label": "Тип бетона для стяжки"},
        {"key": "access", "label": "Есть ли подъезд для техники?"},
        {"key": "depth", "label": "Глубина заложения фундамента?"},
    ]
    out = _filter_card_questions(questions)
    assert [q["key"] for q in out] == ["access", "depth"]


def test_filter_card_questions_keeps_unrelated_material_questions():
    from app.services.ktp_estimate_service import _filter_card_questions

    # «бетон» не упомянут — вопрос остаётся
    questions = [{"key": "brick", "label": "Какая марка кирпича?"}]
    assert _filter_card_questions(questions) == questions


def test_build_stage2_prompt_omits_concrete_example_and_forbids_it():
    from app.services.ktp_estimate_service import _build_stage2_prompt

    group = MagicMock()
    group.id = "g1"
    group.title = "Фундамент"
    prompt = _build_stage2_prompt(group, [], [], None, {})
    assert "concrete_grade" not in prompt
    assert "марку/класс" in prompt


def test_session_subtype_code_is_per_item_and_recoverable():
    from app.services.ktp_estimate_service import (
        UNKNOWN_SUBTYPE_CODE,
        base_subtype_code,
        session_subtype_code,
    )

    it = MagicMock()
    it.id = "item-42"
    # каждая работа — отдельная строка (уникальный код по item.id)
    known = session_subtype_code(it, "2.1")
    unknown = session_subtype_code(it, UNKNOWN_SUBTYPE_CODE)
    assert known == "2.1::item-42"
    assert unknown == f"{UNKNOWN_SUBTYPE_CODE}::item-42"
    # чистый код подтипа восстанавливается для справочника/отображения
    assert base_subtype_code(known) == "2.1"
    assert base_subtype_code(unknown) == UNKNOWN_SUBTYPE_CODE
    # обычный код без суффикса остаётся как есть
    assert base_subtype_code("2.1") == "2.1"


def test_materialize_wbs_handles_ai_added_with_null_row_key():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "A")
    row_keys = {"R1": e1}
    raw_groups = [
        {
            "title": "Кровля",
            "sort_order": 1,
            "work_section_code": "roofing",
            "work_section_name": "Кровельные работы",
            "items": [
                {"name": "A", "origin": "from_estimate", "row_key": "R1"},
                {
                    "name": "Снегозадержатели",
                    "origin": "ai_added",
                    "row_key": None,
                    "review_status": "pending",
                    "ai_reason": "защита",
                },
            ],
        }
    ]
    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)
    assert groups[0].work_section_code == "roofing"
    assert groups[0].work_section_name == "Кровельные работы"
    by_origin = {it.origin: it for it in items}
    assert by_origin["from_estimate"].estimate_id == "e1"
    assert by_origin["ai_added"].estimate_id is None
    assert by_origin["ai_added"].review_status == "pending"
    assert by_origin["ai_added"].ai_reason == "защита"


# ── последовательность групп (2-й уровень) ───────────────────────────────────

def make_group_row(gid: str, title: str, sort_order: float = 1000.0):
    g = MagicMock()
    g.id = gid
    g.title = title
    g.sort_order = sort_order
    return g


def test_is_fallback_group_title_detects_titles():
    from app.services.ktp_estimate_service import _is_fallback_group_title

    assert _is_fallback_group_title("Прочие позиции сметы")
    assert _is_fallback_group_title("Прочие работы сметы")
    assert not _is_fallback_group_title("Фундамент")


def test_reassign_sequence_sort_order_pins_fallback_last():
    from app.services.ktp_estimate_service import _reassign_sequence_sort_order

    a = make_group_row("a", "Земляные")
    b = make_group_row("b", "Фундамент")
    z = make_group_row("z", "Прочие позиции сметы")
    _reassign_sequence_sort_order([b, a], [z])  # порядок b,a

    assert b.sort_order == 1000.0
    assert a.sort_order == 2000.0
    assert z.sort_order == 3000.0  # fallback после всех обычных


@pytest.mark.asyncio
async def test_propose_group_sequence_orders_and_sets_status():
    import app.services.ktp_estimate_service as svc

    session = MagicMock()
    session.status = "gpr_pending"
    groups = [
        make_group_row("a", "Отделка", 1000.0),
        make_group_row("b", "Земляные", 2000.0),
        make_group_row("z", "Прочие позиции сметы", 3000.0),
    ]
    db = AsyncMock()

    with (
        patch.object(svc, "get_session_by_id", AsyncMock(return_value=session)),
        patch.object(svc, "_load_session_groups", AsyncMock(return_value=groups)),
        patch(
            "app.services.ktp_gpr_service._ai_order_groups",
            AsyncMock(return_value=["b", "a"]),  # ИИ: Земляные → Отделка
        ),
        patch.object(svc, "get_wbs", AsyncMock(return_value={"groups": []})),
    ):
        await svc.propose_group_sequence(db, "p1", "s1")

    by_id = {g.id: g for g in groups}
    assert by_id["b"].sort_order == 1000.0
    assert by_id["a"].sort_order == 2000.0
    assert by_id["z"].sort_order == 3000.0  # fallback в конце
    assert session.status == "gpr_sequence_review"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_approve_group_sequence_repins_fallback_and_sets_ready():
    import app.services.ktp_estimate_service as svc

    session = MagicMock()
    session.status = "gpr_sequence_review"
    # оператор по ошибке поставил fallback в середину
    groups = [
        make_group_row("a", "Земляные", 1000.0),
        make_group_row("z", "Прочие позиции сметы", 1500.0),
        make_group_row("b", "Отделка", 2000.0),
    ]
    db = AsyncMock()

    with (
        patch.object(svc, "get_session_by_id", AsyncMock(return_value=session)),
        patch.object(svc, "_load_session_groups", AsyncMock(return_value=groups)),
    ):
        result = await svc.approve_group_sequence(db, "p1", "s1")

    by_id = {g.id: g for g in groups}
    # fallback пере-пинится после максимального обычного (2000) → 3000
    assert by_id["z"].sort_order == 3000.0
    assert session.status == "gpr_ready"
    assert result is session


@pytest.mark.asyncio
async def test_approve_stage1_requires_downstream_operator_review_flag():
    import app.services.ktp_estimate_service as svc
    from app.services.ktp_errors import Stage1ReviewRequired

    session = make_session("s1", "p1")
    session.status = "stage1_review"
    item = MagicMock()
    item.id = "item-1"
    item.estimate_id = "e1"
    item.operator_review_required = True
    item.work_type_needs_review = False
    item.manual_override = False
    estimate = make_est("e1", "Кладка стен")
    estimate.operator_review_required = True
    estimate.classification_needs_review = False
    estimate.needs_review = False
    estimate.raw_data = {"operator_review_required": True}
    estimate.stage_match_score_json = {"needs_review": False, "winner": {"score": 20}, "delta_top_1_top_2": 9}
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=session)
    db.scalars = AsyncMock(return_value=[])
    result_rows = MagicMock()
    result_rows.all.return_value = [(item, estimate)]
    db.execute = AsyncMock(return_value=result_rows)

    with pytest.raises(Stage1ReviewRequired) as exc:
        await svc.approve_stage1(db, "p1", "s1")

    assert exc.value.code == "stage1_review_required"
    assert exc.value.details["problem_items"][0]["item_id"] == "item-1"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_session_subtype_does_not_require_rate_trace_attribute():
    import app.services.ktp_estimate_service as svc

    row = svc.KtpSessionSubtype(
        id="subtype-1",
        session_id="session-1",
        subtype_code="foundation/foundation_rebar_formwork_concrete",
        subtype_name="Фундаментные работы",
        output_per_day=None,
        output_source="default",
        item_id=None,
        rate_unit_conversion=None,
    )
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=row)
    db.commit = AsyncMock()
    expected = {"session": object(), "groups": [], "group_dependencies": [], "session_subtypes": []}

    with patch.object(svc, "get_wbs", AsyncMock(return_value=expected)):
        result = await svc.update_session_subtype(
            db,
            "project-1",
            "subtype-1",
            {
                "output_per_day": 12.5,
                "selected_rate_item_id": "rate-1",
                "selected_rate_mapping_id": "mapping-1",
            },
            user_id="user-1",
        )

    assert result is expected
    assert row.output_per_day == 12.5
    assert row.rate_trace["operator_selection"]["selected_rate_item_id"] == "rate-1"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_session_subtype_unit_updates_linked_item():
    import app.services.ktp_estimate_service as svc

    row = svc.KtpSessionSubtype(
        id="subtype-1",
        session_id="session-1",
        subtype_code="load_bearing_walls/brick_masonry::item-1",
        subtype_name="Кирпичные стены",
        item_id="item-1",
        unit=None,
        volume=100.0,
        output_source="catalog",
        rate_unit_conversion={"conversion_status": "suggested"},
    )
    item = SimpleNamespace(unit=None, quantity=None, quantity_source=None)
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=row)
    db.get = AsyncMock(return_value=item)
    db.commit = AsyncMock()
    expected = {"session": object(), "groups": [], "group_dependencies": [], "session_subtypes": []}

    with patch.object(svc, "get_wbs", AsyncMock(return_value=expected)):
        result = await svc.update_session_subtype(
            db,
            "project-1",
            "subtype-1",
            {"unit": "м2"},
            user_id="user-1",
        )

    assert result is expected
    assert row.unit == "м2"
    assert item.unit == "м2"
    assert item.quantity == 100.0
    assert item.quantity_source == "user"
    assert row.output_source == "default"
    assert row.rate_unit_conversion is None
    db.commit.assert_awaited()
