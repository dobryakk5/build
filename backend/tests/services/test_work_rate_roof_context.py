from __future__ import annotations

import pytest

from app.services.work_rate_models import (
    MAPPING_DIRECT,
    WorkRateItem,
    WorkRateMapping,
    WorkRateSource,
)
from app.services.work_rate_selection_service import WorkRateSelectionService


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
