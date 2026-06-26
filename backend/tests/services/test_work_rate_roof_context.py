from __future__ import annotations

import pytest

from app.services.work_rate_models import (
    MAPPING_DIRECT,
    WorkRateItem,
    WorkRateMapping,
    WorkRateSource,
)
from app.services.work_rate_selection_service import WorkRateSelectionService
from app.services.work_taxonomy_service import detect_operation_detailed


def test_roof_covering_material_context_filters_equivalent_candidates():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_file="Строит-во каркасного дома.xlsx")
    metal = WorkRateItem(
        source_id=source.id,
        name="Монтаж металлочерепицы (крепление саморезами)",
        normalized_name="монтаж металлочерепицы (крепление саморезами)",
        unit_code="m2",
        labor_avg=0.75,
        has_active_mapping=True,
        auto_applicable=True,
        applicability_json={"roof_covering_material": "metal_tile", "base_type": "sparse_batten"},
        row_content_hash="metal-tile",
    )
    flexible = WorkRateItem(
        source_id=source.id,
        name="Монтаж гибкой черепицы (на сплошное основание)",
        normalized_name="монтаж гибкой черепицы (на сплошное основание)",
        unit_code="m2",
        labor_avg=0.94,
        has_active_mapping=True,
        auto_applicable=True,
        applicability_json={"roof_covering_material": "flexible_shingles", "base_type": "solid_deck"},
        row_content_hash="flexible-shingles",
    )
    mappings = [
        WorkRateMapping(
            rate_item_id=metal.id,
            operation_code="roof_covering_installation",
            taxonomy_code="roofing/pitched_roof_covering",
            object_scope_code="roof",
            rate_context_code="metal_tile",
            mapping_mode=MAPPING_DIRECT,
            confidence=0.924,
        ),
        WorkRateMapping(
            rate_item_id=flexible.id,
            operation_code="roof_covering_installation",
            taxonomy_code="roofing/pitched_roof_covering",
            object_scope_code="roof",
            rate_context_code="flexible_shingles",
            mapping_mode=MAPPING_DIRECT,
            confidence=0.924,
        ),
    ]

    result = selector.select_rate(
        taxonomy_code="roofing/pitched_roof_covering",
        operation_code="roof_covering_installation",
        object_scope_code="roof",
        quantity=100,
        unit_code="m2",
        work_name="Металлочерепица",
        items=[metal, flexible],
        mappings=mappings,
        sources=[source],
    )

    assert result.rate_item_id == metal.id
    assert result.rate_context_code == "metal_tile"
    assert result.labor_avg == pytest.approx(0.75)
    assert result.rate_auto_applicable is True


def test_confirmed_volume_to_area_conversion_enables_rate_selection_and_labor():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_file="catalog.xlsx")
    item = WorkRateItem(
        source_id=source.id,
        name="Монтаж опалубки",
        normalized_name="монтаж опалубки",
        unit_code="m2",
        labor_avg=20.0,
        norm_base_quantity=100.0,
        has_active_mapping=True,
        auto_applicable=True,
        row_content_hash="formwork",
    )
    mapping = WorkRateMapping(
        rate_item_id=item.id,
        operation_code="formwork_installation",
        taxonomy_code="foundation/foundation_rebar_formwork_concrete",
        object_scope_code="foundation",
        mapping_mode=MAPPING_DIRECT,
        confidence=0.99,
    )

    blocked = selector.select_rate(
        taxonomy_code="foundation/foundation_rebar_formwork_concrete",
        operation_code="formwork_installation",
        object_scope_code="foundation",
        quantity=12,
        unit_code="m3",
        work_name="Монолитная плита",
        items=[item],
        mappings=[mapping],
        sources=[source],
    )
    assert blocked.review_reason == "unit_incompatible"

    selected = selector.select_rate(
        taxonomy_code="foundation/foundation_rebar_formwork_concrete",
        operation_code="formwork_installation",
        object_scope_code="foundation",
        quantity=12,
        unit_code="m3",
        work_name="Монолитная плита",
        items=[item],
        mappings=[mapping],
        sources=[source],
        unit_conversion_overrides={("m3", "m2"): 5.0},
    )
    assert selected.rate_item_id == item.id
    assert selected.rate_auto_applicable is True

    totals = WorkRateSelectionService.calculate_labor(
        quantity=12,
        quantity_unit="m3",
        rate_item=item,
        unit_conversion_factor_override=5.0,
    )
    assert totals["labor_avg_total"] == pytest.approx(12.0)


def test_operation_detector_prefers_tz_atomic_and_package_rules():
    variant = "residential_construction_kirpichnye_doma"

    excavation = detect_operation_detailed(
        "Разработка котлована экскаватором с погрузкой грунта",
        project_variant_id=variant,
    )
    assert excavation.operation_package_code == "excavation_with_loading_package"
    assert set(excavation.multi_operation_codes) == {"excavation", "soil_loading"}

    formwork = detect_operation_detailed(
        "Монтаж опалубки монолитной фундаментной плиты",
        project_variant_id=variant,
    )
    assert formwork.operation_code == "formwork_installation"

    rebar = detect_operation_detailed(
        "Армирование монолитного перекрытия",
        project_variant_id=variant,
    )
    assert rebar.operation_code == "rebar_installation"

    package = detect_operation_detailed(
        "Устройство монолитного железобетонного перекрытия",
        project_variant_id=variant,
    )
    assert package.operation_package_code == "monolithic_floor_slab_package"


def test_insulation_context_filters_material_before_scoring():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_file="catalog.xlsx")
    mineral = WorkRateItem(
        source_id=source.id,
        name="Утепление фасадных стен минераловатными плитами",
        normalized_name="утепление фасадных стен минераловатными плитами",
        unit_code="m2",
        labor_avg=1.0,
        has_active_mapping=True,
        auto_applicable=True,
        row_content_hash="mineral",
    )
    xps = WorkRateItem(
        source_id=source.id,
        name="Утепление XPS под фундаментной плитой",
        normalized_name="утепление xps под фундаментной плитой",
        unit_code="m2",
        labor_avg=0.5,
        has_active_mapping=True,
        auto_applicable=True,
        row_content_hash="xps",
    )
    mappings = [
        WorkRateMapping(
            rate_item_id=mineral.id,
            operation_code="thermal_insulation",
            taxonomy_code="insulation/facade_wall_insulation",
            mapping_mode=MAPPING_DIRECT,
            confidence=0.92,
        ),
        WorkRateMapping(
            rate_item_id=xps.id,
            operation_code="thermal_insulation",
            taxonomy_code="insulation/facade_wall_insulation",
            mapping_mode=MAPPING_DIRECT,
            confidence=0.92,
        ),
    ]

    result = selector.select_rate(
        taxonomy_code="insulation/facade_wall_insulation",
        operation_code="thermal_insulation",
        object_scope_code=None,
        quantity=50,
        unit_code="m2",
        work_name="Утепление наружных кирпичных стен минераловатными плитами",
        items=[mineral, xps],
        mappings=mappings,
        sources=[source],
    )

    assert result.rate_item_id == mineral.id
    assert result.review_reason is None
