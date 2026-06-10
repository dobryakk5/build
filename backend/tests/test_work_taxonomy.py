import csv
import json
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
    build_precedence_dependencies,
    build_work_section_palette,
    classify_work,
    classify_subtype,
    get_work_taxonomy_sections,
    get_work_taxonomy_subtypes,
)

_DATA = Path(__file__).resolve().parents[1] / "app" / "data" / "work_subtypes.csv"
_DICTIONARY_JSON = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "construction_work_dictionary_v4.json"
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


def _load_json_v4_examples() -> list[tuple[str, dict]]:
    with open(_DICTIONARY_JSON, encoding="utf-8") as fh:
        payload = json.load(fh)
    return [(row["row"], row["expected"]) for row in payload["example_rows"]]


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
def test_classify_work_json_v4_examples(name, expected_section, expected_subtype):
    result = classify_work(name)
    assert result.section_code == expected_section
    assert result.subtype_code == expected_subtype
    assert not result.needs_review


def test_classify_work_related_sections_from_dictionary_rules():
    result = classify_work("Устройство гидроизоляции фундамента битумной мастикой")
    assert result.section_code == "waterproofing"
    assert "foundation" in result.related_sections


@pytest.mark.parametrize("name,expected", _load_json_v4_examples())
def test_classify_work_json_v4_dictionary_examples(name, expected):
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
def test_classify_work_json_v4_conflict_cases(name, expected_section):
    result = classify_work(name)
    assert result.section_code == expected_section


@pytest.mark.asyncio
async def test_work_taxonomy_helpers_fallback_to_json_v4():
    db = MagicMock()
    db.scalars = AsyncMock(return_value=[])

    sections = await get_work_taxonomy_sections(db)
    subtypes = await get_work_taxonomy_subtypes(db)

    assert len(sections) == 19
    assert len(subtypes) == 111
    taxonomy_codes = [s["taxonomy_code"] for s in subtypes]
    assert len(set(taxonomy_codes)) == len(subtypes)
    assert all(code and "." in code for code in taxonomy_codes)
    assert sections[0]["examples"]
    electrical = next(s for s in subtypes if s["work_subtype_code"] == "mep_internal/electrical")
    assert electrical["display_code"] == electrical["legacy_csv_codes"][0] == "7.4"


@pytest.mark.asyncio
async def test_build_work_section_palette_uses_all_sections_when_primary_empty():
    db = MagicMock()
    db.scalars = AsyncMock(return_value=[])
    estimate = SimpleNamespace(raw_data={}, work_section_code=None)

    palette = await build_work_section_palette(db, [estimate])

    assert len(palette) == 19
    assert all(section["is_primary"] for section in palette)


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
