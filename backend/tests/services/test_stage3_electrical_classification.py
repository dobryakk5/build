from __future__ import annotations

import importlib
import re
import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "app"))

from services.excel_work_material_matrix_parser import ExcelWorkMaterialMatrixParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXPECTED_STAGE_BY_SOURCE_NUM = {
    "1": "7.5.3",
    "2": "7.5.5",
    "3": "7.5.5",
    "4": "7.5.21",
    "5": "7.5.19",
    "6": "7.5.19",
    "7": "7.5.19",
    "8": "7.5.19",
    "9": "7.5.19",
    "10": "7.5.20",
    "11": "7.5.20",
    "12": "7.5.4",
    "13": "7.5.4",
    "14": "7.5.18",
    "15": "7.5.8",
    "16": "7.5.4",
    "17": "7.5.4",
    "18": "7.5.18",
    "19": "7.5.8",
    "20": "7.5.6",
    "21": "7.5.8",
    "22": "7.5.8",
    "23": "7.5.8",
    "24": "7.5.18",
    "25": "7.5.18",
    "26": "7.5.18",
    "27": "7.5.18",
    "28": "7.5.9",
    "29": "7.5.9",
    "30": "7.5.10",
    "31": "7.5.10",
    "32": "7.5.9",
    "33": "7.5.9",
    "34": "7.5.9",
    "35": "7.5.9",
    "36": "7.5.16",
}


def _load_services():
    app = sys.modules.setdefault("app", types.ModuleType("app"))
    app.__path__ = getattr(app, "__path__", [])

    models = sys.modules.setdefault("app.models", types.ModuleType("app.models"))
    for name in ("WorkPrecedence", "WorkSubtype"):
        if not hasattr(models, name):
            setattr(models, name, type(name, (), {}))

    app_services = sys.modules.setdefault("app.services", types.ModuleType("app.services"))
    app_services.__path__ = getattr(app_services, "__path__", [])

    taxonomy = importlib.import_module("services.work_taxonomy_service")
    sys.modules["app.services.work_taxonomy_service"] = taxonomy
    stage_classifier = importlib.import_module("services.stage_classifier")
    sys.modules["app.services.stage_classifier"] = stage_classifier
    return taxonomy, stage_classifier


def _classifier_context():
    taxonomy, stage_module = _load_services()
    stages = taxonomy.get_project_variant_stages(
        "internal_mep",
        "internal_mep_montazh_sistem_elektroobespecheniya",
    )
    classifier = stage_module.StageClassifier(taxonomy.get_sequential_scoring_policy())
    return taxonomy, classifier, stages


def test_runtime_dictionary_version_and_electrical_branch() -> None:
    taxonomy, _, stages = _classifier_context()

    taxonomy.assert_project_hierarchy_compatible()
    assert taxonomy.dictionary_version() == "construction_work_dictionary_v6_4_6@1.7.6"
    assert taxonomy.DICTIONARY_SOURCE == "construction_work_dictionary_v6_4_6"
    assert taxonomy.PROMPT_VERSION == "estimate-v6.4.6"
    assert {stage["number"] for stage in stages} >= {
        "7.5.18",
        "7.5.19",
        "7.5.20",
        "7.5.21",
    }


def test_overhead_marker_does_not_capture_surface_mounted_lighting() -> None:
    taxonomy, _, _ = _classifier_context()

    assert taxonomy.classify_row_role(
        "Монтаж накладных светодиодных светильников",
        unit="шт",
        quantity=1,
        allow_absent_header=True,
    ) == "work"
    assert taxonomy.classify_row_role(
        "Светильник накладной",
        unit="шт",
        quantity=1,
        allow_absent_header=True,
    ) != "overhead"
    assert taxonomy.classify_row_role("Накладные расходы", allow_absent_header=True) == "overhead"
    assert taxonomy.classify_row_role("Накладные", allow_absent_header=True) == "overhead"
    assert taxonomy.classify_row_role("ПНР", allow_absent_header=True) == "work"


def test_hierarchy_suggestion_ignores_numeric_ids_and_prefers_7_5() -> None:
    taxonomy, _, _ = _classifier_context()
    rows, _ = ExcelWorkMaterialMatrixParser().parse(FIXTURES / "estimate_building_1.xlsx")
    suggestions = taxonomy.suggest_project_hierarchy_variants(
        [f"{row.section} {row.work_name}" for row in rows],
        limit=5,
    )

    assert suggestions["estimate_types"][0]["id"] == "internal_mep"
    assert suggestions["project_variants"][0]["number"] == "7.5"
    for item in suggestions["estimate_types"] + suggestions["project_variants"]:
        assert all(re.search(r"[A-Za-zА-Яа-яЁё]", term) for term in item["matched_terms"])


def test_shared_primary_work_type_without_explicit_signal_requires_review() -> None:
    taxonomy, classifier, stages = _classifier_context()
    text = "Электромонтаж"
    global_result = taxonomy.classify_work(text, row_role="work")

    first = classifier.classify_row_to_stage(
        text,
        "work",
        stages,
        global_result=global_result,
    )
    second = classifier.classify_row_to_stage(
        text,
        "work",
        list(reversed(stages)),
        global_result=global_result,
    )

    assert first.needs_review is True
    assert second.needs_review is True
    assert first.score_breakdown["auto_accept_gate_passed"] is False
    assert second.score_breakdown["auto_accept_gate_passed"] is False
    assert first.score_breakdown["auto_accept_gate_reason"] == (
        "shared_primary_work_type_without_explicit_stage_evidence"
    )


@pytest.mark.parametrize(
    ("text", "expected_stage"),
    [
        ("Монтаж светодиодных светильников", "7.5.19"),
        ("Монтаж кабельных лотков", "7.5.18"),
        ("Монтаж уличных светильников", "7.5.20"),
        ("ПНР", "7.5.16"),
        ("Монтаж проводников молниезащиты", "7.5.10"),
        ("Монтаж ящиков с понижающим трансформатором", "7.5.21"),
    ],
)
def test_explicit_electrical_stage_examples(text: str, expected_stage: str) -> None:
    taxonomy, classifier, stages = _classifier_context()
    global_result = taxonomy.classify_work(text, row_role="work")
    match = classifier.classify_row_to_stage(
        text,
        "work",
        stages,
        global_result=global_result,
    )

    assert match.stage is not None
    assert match.stage["number"] == expected_stage
    assert match.needs_review is False
    assert match.score_breakdown["explicit_stage_evidence_score"] > 0
    assert match.score_breakdown["auto_accept_gate_passed"] is True


@pytest.mark.parametrize("filename", ["estimate_building_1.xlsx", "estimate_building_2.xlsx"])
def test_all_36_matrix_works_map_to_expected_7_5_stages(filename: str) -> None:
    taxonomy, classifier, stages = _classifier_context()
    rows, _ = ExcelWorkMaterialMatrixParser().parse(FIXTURES / filename)

    actual: dict[str, str] = {}
    for row in rows:
        source_num = row.raw_data["source_num"]
        text = f"{row.section} {row.work_name}"
        assert taxonomy.classify_row_role(
            row.work_name,
            row.section,
            row.unit,
            row.quantity,
            allow_absent_header=True,
        ) == "work"
        global_result = taxonomy.classify_work(text, row_role="work")
        match = classifier.classify_row_to_stage(
            text,
            "work",
            stages,
            global_result=global_result,
        )
        assert match.stage is not None, source_num
        assert match.needs_review is False, (source_num, match.review_reason, match.score_breakdown)
        actual[source_num] = str(match.stage["number"])
        if source_num == "36":
            assert match.work_type_match is not None
            assert match.work_type_match.work_subtype_code == "mep_internal/commissioning"

    assert actual == EXPECTED_STAGE_BY_SOURCE_NUM
