from __future__ import annotations

from app.services.work_rate_models import MAPPING_DIRECT, WorkRateItem, WorkRateMapping, WorkRateSource
from app.services.work_rate_selection_service import WorkRateSelectionService


def test_rate_selection_uses_confirmed_conversion_when_source_unit_missing():
    selector = WorkRateSelectionService()
    source = WorkRateSource(source_file="catalog.xlsx")
    item = WorkRateItem(
        source_id=source.id,
        name="Обратная засыпка пазух",
        normalized_name="обратная засыпка пазух",
        unit_code="m3",
        labor_min=0.4,
        labor_avg=0.5,
        labor_max=0.6,
        has_active_mapping=True,
        auto_applicable=True,
        row_content_hash="backfill",
    )
    mapping = WorkRateMapping(
        rate_item_id=item.id,
        operation_code="backfill",
        taxonomy_code="earthworks/backfill",
        mapping_mode=MAPPING_DIRECT,
        confidence=0.99,
    )

    result = selector.select_rate(
        taxonomy_code="earthworks/backfill",
        operation_code="backfill",
        object_scope_code=None,
        quantity=100,
        unit_code=None,
        items=[item],
        mappings=[mapping],
        sources=[source],
        unit_conversion_overrides={(None, "m3"): 1.0},
    )

    assert result.rate_item_id == item.id
    assert result.unit_code == "m3"
    assert result.rate_auto_applicable is True
    assert result.review_reason is None
