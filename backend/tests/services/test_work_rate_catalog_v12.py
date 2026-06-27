from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.gantt_builder import GanttBuilder
from app.services.work_rate_catalog_service import WorkRateCatalog
from app.services.work_rate_import_service import (
    SafeFormulaEvaluator,
    WorkRateImportService,
    clean_reference_markers,
    normalize_unit,
)
from app.services.upload_service import _infer_operation_from_catalog_mapping
from app.services.work_rate_mapping_service import WorkRateMappingService, adapt_rule
from app.services.work_rate_models import (
    MAPPING_DIRECT,
    MAPPING_OBSERVATION,
    REVIEW_NEEDED,
    SOURCE_OBSERVATION,
    WorkRateCalculationRow,
    WorkRateItem,
    WorkRateMapping,
    WorkRateSource,
)
from app.services.ktp_estimate_service import _catalog_output_per_day, _session_labor_totals
from app.services.work_rate_selection_service import WorkRateSelectionService
from app.services.work_taxonomy_service import (
    get_operation_registry,
    get_operation_object_candidates,
    validate_taxonomy_code,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = BACKEND_ROOT / "app" / "data" / "construction_work_dictionary_v6_5_0.json"
SOURCE_DIR = Path(os.environ.get("WORK_RATE_SOURCE_DIR", "/mnt/data/ref_18_06_unicode"))
NORMALIZED_FILES = [
    "Жилое остальные дома.xlsx",
    "Расценки на ландшафтные работы.xlsx",
    "Расценки №1 11 июня 2026.xlsx",
    "Строит-во каркасного дома.xlsx",
    "Фахверк.xlsx",
]
SOURCE_FILES_AVAILABLE = SOURCE_DIR.is_dir() and all(
    (SOURCE_DIR / name).is_file()
    for name in [*NORMALIZED_FILES, "грунтовые работы.xlsx"]
)
requires_source_files = pytest.mark.skipif(
    not SOURCE_FILES_AVAILABLE,
    reason="Set WORK_RATE_SOURCE_DIR to the source XLSX folder from the work-rate catalog TZ",
)


def test_taxonomy_v650_registry_and_legacy_adapter():
    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    assert payload["dictionary_version"].startswith("construction_work_dictionary_v6_5_0")
    policy = payload["operation_object_resolution_policy"]
    assert policy["version"] == "1.4.0"
    assert isinstance(policy["operations"], dict)
    assert policy["operation_metadata"]["formwork_installation"]["kind"] == "atomic"
    assert policy["operation_metadata"]["formwork_rebar_concrete"]["kind"] == "package"
    assert policy["operation_packages"]["formwork_rebar_concrete"]["legacy"] is True
    assert set(policy["operation_packages"]["monolithic_slab_complete"]["included_operations"]) >= {
        "formwork_installation", "rebar_installation", "concrete_placement", "concrete_vibration"
    }
    adapted = adapt_rule({"operation": "excavation", "object": "foundation", "section_id": "earthworks", "subtype_id": "excavation_pit_trench"})
    assert adapted["operation_code"] == "excavation"
    assert adapted["object_scope_code"] == "foundation"
    assert validate_taxonomy_code("foundation/foundation_rebar_formwork_concrete")
    assert get_operation_object_candidates("formwork_installation", "foundation")
    registry = get_operation_registry()
    assert registry["version"] == "1.4.0"


@requires_source_files
def test_import_all_280_normalized_rows_and_special_units():
    importer = WorkRateImportService()
    results = [importer.import_file(SOURCE_DIR / name) for name in NORMALIZED_FILES]
    assert sum(len(result.items) for result in results) == 280
    assert all(result.source.hourly_rate == 800 for result in results)
    assert normalize_unit("точка")[:2] == ("point", "count_scope")
    assert normalize_unit("проём")[:2] == ("opening", "count_scope")
    assert normalize_unit("участок")[:2] == ("site", "scope")
    assert normalize_unit("окно")[:2] == ("window", "count_scope")
    assert normalize_unit("%")[:2] == ("percent", "ratio")
    assert clean_reference_markers("Монтаж[reference:2][reference:3]") == "Монтаж"


@requires_source_files
def test_observation_import_formulas_roles_and_bad_pile_unit():
    result = WorkRateImportService().import_file(SOURCE_DIR / "грунтовые работы.xlsx")
    assert result.source.source_kind == SOURCE_OBSERVATION
    assert len(result.items) == 16
    physical = [item for item in result.items if item.row_role == "work"]
    excluded = [item for item in result.items if item.mapping_status == "excluded"]
    assert len(physical) == 10
    assert len(excluded) == 6
    excavation = next(item for item in result.items if item.name.startswith("выемка грунта"))
    assert excavation.total_price == pytest.approx(150_000)
    assert excavation.source_payload["formula_diagnostics"]["total_price"]["formula_text"] == "=E13*D13"
    pile = next(item for item in result.items if item.name.startswith("бурение свай"))
    assert pile.unit_code == "m2"


@requires_source_files
def test_import_revision_and_same_file_idempotency():
    path = SOURCE_DIR / "Фахверк.xlsx"
    importer = WorkRateImportService()
    first = importer.import_file(path)
    same = importer.import_file(path, previous_items=first.items)
    assert [item.id for item in same.items] == [item.id for item in first.items]
    changed_previous = list(first.items)
    changed_previous[0].row_content_hash = "different"
    revised = importer.import_file(path, previous_items=changed_previous)
    assert revised.items[0].revision == 2
    assert revised.items[0].supersedes_rate_item_id == first.items[0].id
    assert revised.items[0].review_status == REVIEW_NEEDED


def test_mapping_direct_contextual_package_and_observation_guard():
    mapper = WorkRateMappingService(TAXONOMY)
    formwork = WorkRateItem(name="Монтаж опалубки", normalized_name="монтаж опалубки", unit_code="m2", row_content_hash="1")
    formwork_result = mapper.map_item(formwork)
    assert formwork_result.operation_code == "formwork_installation"
    assert formwork_result.mappings
    assert all(mapping.mapping_mode == "contextual" for mapping in formwork_result.mappings)
    assert formwork.auto_applicable is False

    curb = WorkRateItem(name="Укладка бордюрного камня", normalized_name="укладка бордюрного камня", unit_code="m", row_content_hash="2")
    curb_result = mapper.map_item(curb)
    assert curb_result.operation_code == "curb_installation"
    assert any(mapping.taxonomy_code == "landscape/curbs_edging" for mapping in curb_result.mappings)

    slab = WorkRateItem(name="Устройство монолитного перекрытия с армированием и опалубкой", normalized_name="устройство монолитного перекрытия с армированием и опалубкой", unit_code="m3", row_content_hash="3")
    slab_result = mapper.map_item(slab)
    assert slab_result.operation_code == "monolithic_slab_complete"
    assert slab_result.mappings[0].mapping_mode == "package"

    observation = WorkRateItem(
        name="разработка траншеи экскаватором",
        normalized_name="разработка траншеи экскаватором",
        unit_code="m",
        mapping_status="observation",
        row_content_hash="4",
    )
    observation_result = mapper.map_item(observation)
    assert observation.auto_applicable is False
    assert observation.review_status == REVIEW_NEEDED
    assert all(mapping.mapping_mode == MAPPING_OBSERVATION for mapping in observation_result.mappings)


def test_pile_drilling_bad_unit_requires_review():
    mapper = WorkRateMappingService(TAXONOMY)
    item = WorkRateItem(name="Бурение под сваи", normalized_name="бурение под сваи", unit_code="m2", row_content_hash="1")
    result = mapper.map_item(item)
    assert result.operation_code == "pile_drilling"
    assert item.review_status == REVIEW_NEEDED
    assert item.review_reason == "operation_unit_conflict"
    assert item.auto_applicable is False


def test_selection_never_auto_uses_unapproved_observation():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_kind=SOURCE_OBSERVATION, source_file="x.xlsx")
    item = WorkRateItem(
        source_id=source.id,
        name="Разработка грунта",
        normalized_name="разработка грунта",
        unit_code="m3",
        labor_avg=1.0,
        has_active_mapping=True,
        approved_as_rate=False,
        row_content_hash="x",
    )
    mapping = WorkRateMapping(
        rate_item_id=item.id,
        operation_code="excavation",
        taxonomy_code="earthworks/excavation_pit_trench",
        object_scope_code="construction_site",
        mapping_mode="observation",
        confidence=0.99,
    )
    result = selector.select_rate(
        taxonomy_code="earthworks/excavation_pit_trench",
        operation_code="excavation",
        object_scope_code="construction_site",
        quantity=10,
        unit_code="m3",
        items=[item], mappings=[mapping], sources=[source],
    )
    assert result.rate_item_id is None
    assert result.needs_review
    item.approved_as_rate = True
    approved = selector.select_rate(
        taxonomy_code="earthworks/excavation_pit_trench",
        operation_code="excavation",
        object_scope_code="construction_site",
        quantity=10,
        unit_code="m3",
        items=[item], mappings=[mapping], sources=[source],
    )
    assert approved.rate_item_id == item.id
    assert approved.selection_source == "project_specific"


def test_labor_priority_manual_and_modes():
    resolve = WorkRateSelectionService.resolve_labor_source
    manual = resolve(
        labor_source_mode="hybrid",
        manual_labor_hours=77,
        project_specific_labor_hours=50,
        catalog_independent_labor_hours=40,
        fer_labor_hours=30,
        catalog_derived_labor_hours=20,
    )
    assert manual.resolved_labor_hours == 77
    assert manual.resolved_labor_source == "manual"
    hybrid = resolve(
        labor_source_mode="hybrid",
        project_specific_labor_hours=None,
        catalog_independent_labor_hours=40,
        fer_labor_hours=30,
        catalog_derived_labor_hours=20,
    )
    assert hybrid.resolved_labor_hours == 40
    fer = resolve(labor_source_mode="fer", fer_labor_hours=30, catalog_derived_labor_hours=20)
    assert fer.resolved_labor_source == "fer"


def test_labor_resolution_no_longer_uses_subtype_output_fallback():
    result = WorkRateSelectionService.resolve_labor_source(labor_source_mode="rate_catalog")
    assert result.resolved_labor_hours is None
    assert result.resolved_labor_source is None
    assert result.needs_review is True
    assert result.reason == "labor_source_not_available"


def test_rate_selection_exposes_unit_conversion_for_kg_to_t():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_file="catalog.xlsx")
    item = WorkRateItem(
        source_id=source.id,
        name="Металлоконструкции",
        normalized_name="металлоконструкции",
        unit_code="t",
        labor_min=8,
        labor_avg=10,
        labor_max=12,
        has_active_mapping=True,
        auto_applicable=True,
        row_content_hash="metal",
    )
    mapping = WorkRateMapping(
        rate_item_id=item.id,
        operation_code="steel_installation",
        taxonomy_code="metal/steel_structures",
        mapping_mode=MAPPING_DIRECT,
        confidence=0.99,
    )
    result = selector.select_rate(
        taxonomy_code="metal/steel_structures",
        operation_code="steel_installation",
        object_scope_code=None,
        quantity=500,
        unit_code="kg",
        items=[item],
        mappings=[mapping],
        sources=[source],
    )
    assert result.rate_item_id == item.id
    assert result.item_unit_code == "kg"
    assert result.rate_unit_code == "t"
    assert result.unit_conversion_factor == pytest.approx(0.001)
    assert result.rate_auto_applicable is True


def test_rate_selection_blocks_not_auto_applicable_rate_for_productivity():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_file="catalog.xlsx")
    item = WorkRateItem(
        source_id=source.id,
        name="Контекстная расценка",
        normalized_name="контекстная расценка",
        unit_code="m2",
        labor_avg=1.5,
        has_active_mapping=True,
        auto_applicable=False,
        review_reason="contextual_mapping_requires_object",
        row_content_hash="contextual",
    )
    mapping = WorkRateMapping(
        rate_item_id=item.id,
        operation_code="painting",
        taxonomy_code="interior_finishing/painting",
        mapping_mode=MAPPING_DIRECT,
        confidence=0.99,
    )
    result = selector.select_rate(
        taxonomy_code="interior_finishing/painting",
        operation_code="painting",
        object_scope_code=None,
        quantity=100,
        unit_code="m2",
        items=[item],
        mappings=[mapping],
        sources=[source],
    )
    assert result.rate_item_id == item.id
    assert result.rate_auto_applicable is False
    assert result.needs_review is True
    assert result.review_reason == "contextual_mapping_requires_object"


def test_infer_operation_from_catalog_mapping_requires_single_auto_applicable_operation():
    auto_item = WorkRateItem(
        name="Укладка труб тёплого пола",
        unit_code="m2",
        labor_avg=0.69,
        has_active_mapping=True,
        auto_applicable=True,
        row_content_hash="heating",
    )
    blocked_item = WorkRateItem(
        name="Контекстная расценка",
        unit_code="m2",
        labor_avg=1.0,
        has_active_mapping=True,
        auto_applicable=False,
        row_content_hash="blocked",
    )
    mappings = [
        WorkRateMapping(
            rate_item_id=auto_item.id,
            operation_code="underfloor_heating_pipe_installation",
            taxonomy_code="mep_internal/heating",
            mapping_mode=MAPPING_DIRECT,
            confidence=0.99,
        ),
        WorkRateMapping(
            rate_item_id=blocked_item.id,
            operation_code="radiator_installation",
            taxonomy_code="mep_internal/heating",
            mapping_mode=MAPPING_DIRECT,
            confidence=0.99,
        ),
    ]
    operation_code, object_scope_code = _infer_operation_from_catalog_mapping(
        taxonomy_code="mep_internal/heating",
        unit_code="m2",
        object_scope_code=None,
        mappings=mappings,
        item_by_id={auto_item.id: auto_item, blocked_item.id: blocked_item},
    )
    assert operation_code == "underfloor_heating_pipe_installation"
    assert object_scope_code is None


def test_catalog_output_uses_effective_labor_hours_per_item_unit():
    raw = {
        "selected_rate_item_id": "rate-1",
        "rate_auto_applicable": True,
        "labor_hours_per_unit_min": 8,
        "labor_hours_per_unit_avg": 10,
        "labor_hours_per_unit_max": 12,
        "unit_conversion_factor": 0.001,
    }
    output, source = _catalog_output_per_day(raw, crew_size=4, hours_per_day=8)
    assert output == pytest.approx(3200)
    assert source == "catalog"
    totals = _session_labor_totals(raw, 500)
    assert totals["min"] == pytest.approx(4)
    assert totals["avg"] == pytest.approx(5)
    assert totals["max"] == pytest.approx(6)


def test_catalog_output_empty_for_incompatible_units():
    raw = {
        "selected_rate_item_id": "rate-1",
        "rate_auto_applicable": False,
        "labor_hours_per_unit_avg": 10,
        "unit_conversion_factor": None,
        "rate_review_reason": "unit_incompatible",
    }
    output, source = _catalog_output_per_day(raw, crew_size=4, hours_per_day=8)
    assert output is None
    assert source == "none"


def test_group_level_package_conflict():
    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    selector = WorkRateSelectionService(payload["operation_object_resolution_policy"]["operation_packages"])
    rows = [
        WorkRateCalculationRow("1", "group-a", "formwork_rebar_concrete", rate_item_id="pkg"),
        WorkRateCalculationRow("2", "group-a", "formwork_installation", rate_item_id="form"),
        WorkRateCalculationRow("3", "group-a", "rebar_installation", rate_item_id="rebar"),
        WorkRateCalculationRow("4", "group-b", "concrete_placement", rate_item_id="other"),
    ]
    conflicts = selector.detect_package_conflicts(rows)
    assert len(conflicts) == 1
    assert conflicts[0].calculation_group_key == "group-a"
    assert set(conflicts[0].conflicting_operation_codes) == {"formwork_installation", "rebar_installation"}


def test_gantt_uses_manual_then_resolved_labor():
    builder = GanttBuilder()
    manual = SimpleNamespace(
        id="1", labor_hours=2, quantity=10, fer_table_id=None, total_price=None,
        work_name="Работа", raw_data={"resolved_labor_hours": 999},
    )
    assert builder._calc_labor_hours(manual, 3, 8, {}) == 20
    resolved = SimpleNamespace(
        id="2", labor_hours=None, quantity=10, fer_table_id=None, total_price=None,
        work_name="Неизвестная операция", raw_data={"resolved_labor_hours": 55},
    )
    assert builder._calc_labor_hours(resolved, 3, 8, {}) == 55


@requires_source_files
def test_initial_catalog_import_has_all_statuses(tmp_path):
    catalog = WorkRateCatalog()
    for name in NORMALIZED_FILES + ["грунтовые работы.xlsx"]:
        catalog.import_file(SOURCE_DIR / name)
    mapper = WorkRateMappingService(TAXONOMY)
    catalog.auto_map(mapper)
    assert len(catalog.items) == 296
    assert sum(1 for item in catalog.items if item.source_id in {source.id for source in catalog.sources if source.source_kind != SOURCE_OBSERVATION}) == 280
    assert all(item.mapping_status for item in catalog.items)
    out = tmp_path / "catalog.json"
    catalog.save(out)
    loaded = WorkRateCatalog.load(out)
    assert len(loaded.items) == len(catalog.items)
    counts = Counter(item.mapping_status for item in loaded.items)
    assert sum(counts.values()) == 296


def test_upload_rate_enrichment_attaches_catalog_labor():
    from app.services.excel_parser import ParsedRow
    from app.services.upload_service import _enrich_work_rates_sync

    row = ParsedRow(
        section="Чистовая планировка",
        work_name="Планировка участка",
        unit="м2",
        quantity=10,
        raw_data={
            "row_role": "work",
            "work_type_applicable": True,
            "work_subtype_code": "landscape/landscape_grading",
            "operation_code": "landscape_grading",
            "selected_object_scope_code": "landscape_site",
            "section_block_id": "block-grading",
        },
    )
    _enrich_work_rates_sync(
        [row],
        {"labor_source_mode": "rate_catalog", "project_id": "project-test"},
    )
    raw = row.raw_data
    assert raw["selected_rate_item_id"]
    assert raw["selected_rate_mapping_id"]
    assert raw["resolved_labor_source"] == "catalog_derived"
    assert raw["calculated_labor_hours_avg"] == pytest.approx(2.7)
    assert raw["resolved_labor_hours"] == pytest.approx(2.7)
    assert raw["rate_needs_review"] is False
