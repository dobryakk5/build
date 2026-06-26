from __future__ import annotations

from app.services.work_rate_models import (
    MAPPING_DIRECT,
    WorkRateItem,
    WorkRateMapping,
    WorkRateSource,
)
from app.services.work_rate_selection_service import WorkRateSelectionService


def test_brick_masonry_uses_text_context_before_applicability_filter():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_file="catalog.xlsx")
    item = WorkRateItem(
        source_id=source.id,
        name="Кладка кирпича (внутренние несущие стены)",
        normalized_name="кладка кирпича внутренние несущие стены",
        unit_code="m3",
        labor_avg=4.38,
        has_active_mapping=True,
        auto_applicable=True,
        row_content_hash="brick-interior",
    )
    mapping = WorkRateMapping(
        rate_item_id=item.id,
        operation_code="brick_masonry",
        taxonomy_code="load_bearing_walls/brick_masonry",
        rate_context_code="interior_wall",
        mapping_mode=MAPPING_DIRECT,
        confidence=0.92,
    )

    result = selector.select_rate(
        taxonomy_code="load_bearing_walls/brick_masonry",
        operation_code="brick_masonry",
        object_scope_code=None,
        quantity=32.6,
        unit_code="m3",
        work_name="Кладка внутренних несущих стен первого этажа из силикатного кирпича толщиной 380 мм",
        items=[item],
        mappings=[mapping],
        sources=[source],
    )

    assert result.rate_item_id == item.id
    assert result.rate_context_code == "interior_wall"
    assert result.rate_auto_applicable is True
    assert result.needs_review is False
