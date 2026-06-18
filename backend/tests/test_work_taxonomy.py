import csv
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.work_taxonomy_service import (  # noqa: E402
    PrecedenceEdge,
    SubtypeDef,
    _score_subtype,
    build_precedence_dependencies,
    build_work_section_palette,
    classify_row_role,
    classify_work,
    classify_subtype,
    dictionary_version,
    get_project_hierarchy,
    get_project_variant_stages,
    get_work_taxonomy_sections,
    get_work_taxonomy_subtypes,
    legacy_estimate_kind_for_type,
    should_inherit_parent_context,
    validate_dictionary_payload,
    validate_project_hierarchy_selection,
)
from app.services.stage_classifier import StageClassifier  # noqa: E402

_DATA = Path(__file__).resolve().parents[1] / "app" / "data" / "work_subtypes.csv"
_DICTIONARY_JSON = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "construction_work_dictionary_v6_4_draft.json"
)


def _load_taxonomy_from_csv() -> list[SubtypeDef]:
    with open(_DATA, encoding="utf-8") as fh:
        return [
            SubtypeDef(
                macro_id=int(r["macro_id"]),
                code=r["subtype_code"],
                name=r["subtype_name"],
                keywords=tuple(k.strip().lower() for k in r["keywords"].split(";") if k.strip()),
            )
            for r in csv.DictReader(fh)
        ]


TAXONOMY = _load_taxonomy_from_csv()


def _load_json_examples() -> list[tuple[str, dict]]:
    with open(_DICTIONARY_JSON, encoding="utf-8") as fh:
        payload = json.load(fh)
    valid_codes = {
        f"{section['id']}/{subtype['id']}"
        for section in payload["sections"]
        for subtype in section.get("subtypes") or []
    }
    return [
        (row.get("row") or row.get("text"), row["expected"])
        for row in payload["example_rows"]
        if row.get("row") or row.get("text")
        if f"{row['expected']['section_id']}/{row['expected']['subtype_id']}" in valid_codes
    ]


@pytest.mark.parametrize(
    "name,expected_code",
    [
        ("Штукатурка стен", "5.1"),
        ("Трубы отопления, монтаж", "7.2"),
        ("Засыпка пазух грунтом", "1.3"),
        ("Устройство кровли из ондулина", "2.5"),
    ],
)
def test_classify_subtype_matches_expected(name, expected_code):
    match = classify_subtype(name, None, TAXONOMY)
    assert match is not None
    assert match.code == expected_code


def test_classify_subtype_returns_none_when_no_keyword():
    assert classify_subtype("Прочие непредвиденные затраты по объекту", None, TAXONOMY) is None


def test_classify_subtype_prefers_more_specific_keyword():
    # "засыпка пазух" + "засыпка грунтом" → два совпадения по 1.3 против одного у соседей
    match = classify_subtype("Обратная засыпка пазух грунтом", None, TAXONOMY)
    assert match is not None
    assert match.code == "1.3"


@pytest.mark.parametrize(
    "name,expected_section,expected_subtype",
    [
        (
            "Разработка грунта в котловане экскаватором с погрузкой в самосвалы",
            "earthworks",
            "earthworks/excavation_pit_trench",
        ),
        (
            "Устройство гидроизоляции фундамента битумной мастикой в 2 слоя",
            "waterproofing",
            "waterproofing/coating_waterproofing",
        ),
        (
            "Монтаж плит перекрытия ПК с заделкой швов раствором",
            "floor_slabs",
            "floor_slabs/precast_rc_slabs",
        ),
        (
            "Устройство кровельного ковра из ПВХ-мембраны с примыканием к парапетам",
            "roofing",
            "roofing/flat_roll_membrane_roof",
        ),
        (
            "Монтаж перегородок из ГКЛ по металлическому каркасу с заполнением минватой",
            "partitions",
            "partitions/drywall_partitions",
        ),
        (
            "Устройство полусухой стяжки пола с фиброармированием и затиркой вертолетом",
            "floor_screed",
            "floor_screed/semi_dry_screed",
        ),
    ],
)
def test_classify_work_json_v6_4_examples(name, expected_section, expected_subtype):
    result = classify_work(name)
    assert result.section_code == expected_section
    assert result.subtype_code == expected_subtype
    assert not result.needs_review


def test_classify_work_related_sections_from_dictionary_rules():
    result = classify_work("Устройство гидроизоляции фундамента битумной мастикой")
    assert result.section_code == "waterproofing"
    assert "foundation" in result.related_sections


@pytest.mark.parametrize("name,expected", _load_json_examples())
def test_classify_work_json_v6_4_dictionary_examples(name, expected):
    result = classify_work(name)
    expected_subtype = f"{expected['section_id']}/{expected['subtype_id']}"
    assert result.section_code == expected["section_id"]
    assert result.subtype_code == expected_subtype
    for related_section in expected.get("related_sections") or []:
        assert related_section in result.related_sections


@pytest.mark.parametrize(
    "name,expected_section",
    [
        ("Устройство ПВХ-мембраны по кровле с примыканием к парапету", "roofing"),
        ("Полусухая стяжка пола с фиброармированием", "floor_screed"),
        ("Армирование монолитной плиты перекрытия", "floor_slabs"),
        ("Бетонирование ленточного фундамента", "foundation"),
        ("Кладка несущих стен из газоблока", "load_bearing_walls"),
        ("Монтаж перегородок из пеноблока", "partitions"),
        ("Вязка арматуры монолитных колонн и ригелей", "structural_frame"),
    ],
)
def test_classify_work_json_v6_4_conflict_cases(name, expected_section):
    result = classify_work(name)
    assert result.section_code == expected_section


@pytest.mark.parametrize(
    "name,expected_subtype",
    [
        ("Мягкая отмостка из профилированной мембраны", "landscape/soft_blind_area"),
        ("Основание пошаговых плит в газоне", "landscape/stepping_stone_base"),
        ("Уголок металлический по прямолинейным периметрам мощения", "landscape/curbs_edging"),
        ("Мощение брусчаткой гранитной", "landscape/granite_paving"),
        ("Укладка крупноформатных плит", "landscape/large_format_stone_paving"),
        ("Облицовка крышки подпорной стенки", "landscape/natural_stone_cladding"),
        ("Формирование корыта разработка грунта", "earthworks/forming_trough"),
        ("Перемещение вынутого грунта в пределах участка", "earthworks/terrain_reshaping"),
    ],
)
def test_classify_work_json_v6_4_landscape_smoke_cases(name, expected_subtype):
    result = classify_work(name)
    assert result.subtype_code == expected_subtype
    assert not result.needs_review


def test_score_subtype_negative_term_reduces_score_and_is_audited():
    weights = {"subtype_strong_term": 5, "negative_term": -6}
    haystack = "формирование корыта под брусчатку"
    hay_tokens = haystack.split()
    subtype = {
        "id": "forming_trough",
        "strong_terms": ["формирование корыта"],
        "negative_terms": ["брусчатка"],
    }

    score, matched = _score_subtype(subtype, haystack, hay_tokens, weights)
    score_without_negative, matched_without_negative = _score_subtype(
        {**subtype, "negative_terms": []},
        haystack,
        hay_tokens,
        weights,
    )

    assert matched["subtype_strong_terms"] == ["формирование корыта"]
    assert matched["subtype_negative_terms"] == ["брусчатка"]
    assert score == -1
    assert score < score_without_negative
    assert "subtype_negative_terms" not in matched_without_negative


def test_score_subtype_negative_term_does_not_affect_other_subtype():
    weights = {"subtype_strong_term": 5, "negative_term": -6}
    haystack = "формирование корыта под брусчатку"
    hay_tokens = haystack.split()

    penalized_score, penalized_matched = _score_subtype(
        {
            "id": "forming_trough",
            "strong_terms": ["формирование корыта"],
            "negative_terms": ["брусчатка"],
        },
        haystack,
        hay_tokens,
        weights,
    )
    other_score, other_matched = _score_subtype(
        {
            "id": "paving",
            "strong_terms": ["брусчатка"],
            "negative_terms": [],
        },
        haystack,
        hay_tokens,
        weights,
    )

    assert penalized_matched["subtype_negative_terms"] == ["брусчатка"]
    assert "subtype_negative_terms" not in other_matched
    assert penalized_score < other_score


@pytest.mark.parametrize("name", ["Транспортные расходы", "Накладные расходы"])
def test_classify_work_json_v6_4_overhead_rows_do_not_create_work_subtype(name):
    result = classify_work(name)
    assert classify_row_role(name) == "overhead"
    assert result.subtype_code == "unknown/needs_review"
    assert result.source == "row_role_overhead"
    assert not result.needs_review


def test_classify_work_json_v6_4_row_role_policy():
    assert classify_row_role("БЛАГОУСТРОЙСТВО", allow_absent_header=True) == "header"
    assert classify_row_role("Услуги геодезиста", section="Начальные работы") != "work"
    assert should_inherit_parent_context("material", "Профилированная мембрана") is True
    assert should_inherit_parent_context("overhead", "Транспортные расходы") is False


def test_upload_row_role_uses_explicit_item_type_before_heuristics():
    from app.services.upload_service import _row_role_from_item_type

    assert _row_role_from_item_type("work", "Накладные расходы") == "work"
    assert _row_role_from_item_type("material", "Монтаж перегородок") == "material"
    assert _row_role_from_item_type("mechanism", "Экскаватор") == "mechanism"
    assert _row_role_from_item_type("overhead", "Транспортные расходы") == "overhead"
    assert _row_role_from_item_type("overhead", "Доставка материалов") == "logistics"


@pytest.mark.asyncio
async def test_work_taxonomy_helpers_fallback_to_json_v6_4():
    db = MagicMock()
    db.scalars = AsyncMock(return_value=[])

    sections = await get_work_taxonomy_sections(db)
    subtypes = await get_work_taxonomy_subtypes(db)

    assert len(sections) == 19
    assert len(subtypes) == 218
    assert dictionary_version() == "construction_work_dictionary_v6_4_2_type2_7_patch@1.7.2"
    taxonomy_codes = [s["taxonomy_code"] for s in subtypes]
    assert len(set(taxonomy_codes)) == len(subtypes)
    assert all(code and "." in code for code in taxonomy_codes)
    assert sections[0]["examples"]
    electrical = next(s for s in subtypes if s["work_subtype_code"] == "mep_internal/electrical")
    assert electrical["display_code"] == electrical["legacy_csv_codes"][0] == "7.4"


def test_project_hierarchy_exposes_types_and_variants():
    hierarchy = get_project_hierarchy()
    assert hierarchy["dictionary_version"] == "construction_work_dictionary_v6_4_2_type2_7_patch@1.7.2"
    assert len(hierarchy["estimate_types"]) == 9
    assert sum(len(t["project_variants"]) for t in hierarchy["estimate_types"]) == 65
    assert sum(
        variant["stages_count"]
        for t in hierarchy["estimate_types"]
        for variant in t["project_variants"]
    ) == 1043
    residential = next(t for t in hierarchy["estimate_types"] if t["id"] == "residential_construction")
    assert residential["estimate_kind"] == 2
    assert any(
        variant["number"] == "2.6"
        and variant["title"] == "Дома из пено- или газоблоков"
        for variant in residential["project_variants"]
    )


def test_dictionary_validator_rejects_grouped_all_without_stage_options():
    with open(_DICTIONARY_JSON, encoding="utf-8") as fh:
        payload = json.load(fh)
    broken = deepcopy(payload)

    for estimate_type in broken["project_hierarchy"]["estimate_types"]:
        for variant in estimate_type.get("project_variants") or []:
            for stage in variant.get("stages") or []:
                if stage.get("stage_options_mode") == "grouped_all":
                    stage["stage_options"] = []
                    with pytest.raises(RuntimeError, match="grouped_all without stage_options"):
                        validate_dictionary_payload(broken)
                    return

    pytest.fail("No grouped_all stage found in dictionary fixture")


def test_project_hierarchy_selection_validates_parent_variant_and_legacy_kind():
    selection = validate_project_hierarchy_selection(
        "residential_construction",
        "residential_construction_doma_iz_peno_ili_gazoblokov",
    )
    assert selection["estimate_kind"] == 2
    assert selection["project_variant_number"] == "2.6"
    assert legacy_estimate_kind_for_type("landscape_hardscape") == 9
    by_number = validate_project_hierarchy_selection("residential_construction", "2.6")
    assert by_number["project_variant_id"] == "residential_construction_doma_iz_peno_ili_gazoblokov"

    with pytest.raises(ValueError):
        validate_project_hierarchy_selection(
            "site_earthworks",
            "residential_construction_doma_iz_peno_ili_gazoblokov",
        )


@pytest.mark.asyncio
async def test_build_work_section_palette_uses_all_sections_when_primary_empty():
    db = MagicMock()
    db.scalars = AsyncMock(return_value=[])
    estimate = SimpleNamespace(raw_data={}, work_section_code=None)

    palette = await build_work_section_palette(db, [estimate])

    assert len(palette) == 19
    assert all(section["is_primary"] for section in palette)


@pytest.mark.parametrize(
    "row_text,expected_stage,expected_section,expected_subtype,expected_option,expected_occurrence",
    [
        (
            "Кладка стен из газоблока 400 мм на клеевой раствор",
            "2.6.6",
            "load_bearing_walls",
            "block_walls",
            None,
            "1 этаж",
        ),
        (
            "Армирование кладки 1 этажа сеткой",
            "2.6.7",
            "load_bearing_walls",
            "arm_belts_lintels",
            None,
            "1 этаж",
        ),
        (
            "Кладка стен 2 этажа из газоблока",
            "2.6.10",
            "load_bearing_walls",
            "block_walls",
            None,
            "2 этаж",
        ),
        (
            "Устройство утепленной шведской плиты",
            "2.6.2",
            "foundation",
            "slab_foundation",
            "УШП",
            None,
        ),
        (
            "Устройство деревянного перекрытия цоколя",
            "2.6.5",
            "floor_slabs",
            "timber_floor",
            "Деревянный",
            None,
        ),
        (
            "Монтаж стропильной системы",
            "2.6.14",
            "rafters",
            "rafters_installation",
            "Стропильная система",
            None,
        ),
        (
            "Монтаж металлочерепицы",
            "2.6.14",
            "roofing",
            "pitched_roof_covering",
            "Кровельное покрытие",
            None,
        ),
    ],
)
def test_stage_classifier_gas_block_house_regressions(
    row_text,
    expected_stage,
    expected_section,
    expected_subtype,
    expected_option,
    expected_occurrence,
):
    stages = get_project_variant_stages("residential_construction", "2.6")
    match = StageClassifier().classify_row_to_stage(row_text, "work", stages, None)
    raw = match.as_raw_data(
        estimate_type_id="residential_construction",
        estimate_type_number="2",
        project_variant_id="residential_construction_doma_iz_peno_ili_gazoblokov",
        project_variant_number="2.6",
        row_role="work",
    )

    assert match.stage is not None
    assert match.stage["number"] == expected_stage
    assert raw["section_id"] == expected_section
    assert raw["subtype_id"] == expected_subtype
    if expected_option:
        assert match.stage_option is not None
        assert match.stage_option["title"] == expected_option
    if expected_occurrence:
        assert match.stage["occurrence_label"] == expected_occurrence


def test_stage_classifier_material_inherits_previous_stage():
    stages = get_project_variant_stages("residential_construction", "2.6")
    classifier = StageClassifier()
    work = classifier.classify_row_to_stage("Кладка стен из газоблока", "work", stages, None)
    context = work.as_raw_data(
        estimate_type_id="residential_construction",
        estimate_type_number="2",
        project_variant_id="residential_construction_doma_iz_peno_ili_gazoblokov",
        project_variant_number="2.6",
        row_role="work",
    )

    material = classifier.classify_row_to_stage("Газоблок D500", "material", stages, context)
    glue = classifier.classify_row_to_stage("Клей для газоблока", "material", stages, context)

    assert material.stage is not None
    assert glue.stage is not None
    assert material.stage["number"] == glue.stage["number"] == "2.6.6"
    assert material.match_type == glue.match_type == "material_inherit"


def test_build_precedence_dependencies_basic_with_lag():
    subtype_to_task_ids = {"2.2": ["A"], "2.3": ["B"]}
    precedence = [PrecedenceEdge("2.2", "2.3", 3)]
    edges = build_precedence_dependencies(subtype_to_task_ids, precedence)
    assert edges == [("B", "A", 3)]  # successor depends_on predecessor, lag=3


def test_build_precedence_dependencies_representative_selection():
    # последняя задача предшественника → первая задача последователя
    subtype_to_task_ids = {"2.3": ["B1", "B2"], "2.8": ["C1", "C2"]}
    precedence = [PrecedenceEdge("2.3", "2.8", 0)]
    edges = build_precedence_dependencies(subtype_to_task_ids, precedence)
    assert edges == [("C1", "B2", 0)]


def test_build_precedence_dependencies_skips_missing_subtypes():
    subtype_to_task_ids = {"2.2": ["A"]}  # 2.3 отсутствует
    precedence = [PrecedenceEdge("2.2", "2.3", 3)]
    assert build_precedence_dependencies(subtype_to_task_ids, precedence) == []


@pytest.mark.asyncio
async def test_resolve_project_dates_applies_lag():
    from app.services.gantt_service import resolve_project_dates

    pred = SimpleNamespace(id="pred", project_id="p", start_date=date(2026, 6, 1), working_days=2)
    succ = SimpleNamespace(id="succ", project_id="p", start_date=date(2026, 6, 1), working_days=1)
    dep = SimpleNamespace(task_id="succ", depends_on="pred", lag_days=3)

    db = MagicMock()
    db.scalars = AsyncMock(return_value=iter([pred, succ]))
    exec_result = MagicMock()
    exec_result.scalars.return_value = [dep]
    db.execute = AsyncMock(return_value=exec_result)
    db.add = MagicMock()

    changed = await resolve_project_dates("p", db)

    # pred заканчивается 2026-06-03, +3 дня лага → succ стартует 2026-06-06
    assert {"id": "succ", "start_date": "2026-06-06"} in changed
    assert succ.start_date == date(2026, 6, 6)
