from decimal import Decimal

import pytest

from app.services.user_work_rate_service import (
    UserWorkRateRecord,
    build_work_rate_key,
    validate_labor_hours,
)
from app.services.gantt_builder import GanttBuilder
from app.services.gantt_calculations import calculate_working_days
from app.services.work_rate_models import (
    MAPPING_DIRECT,
    SOURCE_NORMATIVE,
    WorkRateItem,
    WorkRateMapping,
    WorkRateSource,
)
from app.services.work_rate_selection_service import WorkRateSelectionService


def user_rate(**changes):
    values = {
        "id": "user-rate-1",
        "user_id": "user-1",
        "taxonomy_code": "finishing/wall_plastering",
        "operation_code": "wall_plastering",
        "object_scope_code": "internal_wall",
        "rate_context_code": None,
        "rate_variant_code": None,
        "unit_code": "m2",
        "labor_hours_per_unit": Decimal("0.850000"),
        "work_name_snapshot": "Штукатурка стен",
    }
    values.update(changes)
    return UserWorkRateRecord(**values)


def select(*, items=(), mappings=(), sources=(), rates=(), unit="m2", scope="internal_wall", applicability=None):
    return WorkRateSelectionService().select_rate(
        taxonomy_code="finishing/wall_plastering",
        operation_code="wall_plastering",
        object_scope_code=scope,
        rate_context_code=(applicability or {}).get("rate_context_code"),
        quantity=100,
        unit_code=unit,
        work_name="Штукатурка внутренних стен",
        items=items,
        mappings=mappings,
        sources=sources,
        user_id="user-1",
        user_rates=rates,
        applicability=applicability or {},
    )


@pytest.mark.parametrize("field", ["taxonomy_code", "operation_code", "unit_code"])
def test_work_rate_key_requires_canonical_fields(field):
    values = {
        "taxonomy_code": "finishing/wall_plastering",
        "operation_code": "wall_plastering",
        "object_scope_code": None,
        "rate_context_code": None,
        "rate_variant_code": None,
        "unit_code": "m2",
    }
    values[field] = None
    with pytest.raises(ValueError, match=f"{field}_required"):
        build_work_rate_key(**values)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", 0, -1])
def test_labor_hours_must_be_finite_and_positive(value):
    with pytest.raises(ValueError):
        validate_labor_hours(value)


def test_inactive_user_rate_remains_in_key_space_but_is_not_selected():
    result = select(rates=[user_rate(is_active=False)])
    assert result.status == "needs_user_rate"
    assert result.rate_source is None


def test_global_rate_has_priority_over_user_rate():
    source = WorkRateSource(id="source-1", source_kind=SOURCE_NORMATIVE)
    item = WorkRateItem(
        id="global-1",
        source_id=source.id,
        name="Штукатурка",
        unit_code="m2",
        labor_min=0.7,
        labor_avg=0.7,
        labor_max=0.7,
        labor_basis="normative",
        has_active_mapping=True,
        auto_applicable=True,
    )
    mapping = WorkRateMapping(
        id="mapping-1",
        rate_item_id=item.id,
        taxonomy_code="finishing/wall_plastering",
        operation_code="wall_plastering",
        object_scope_code="internal_wall",
        rate_context_code=None,
        mapping_mode=MAPPING_DIRECT,
        confidence=1.0,
    )

    result = select(items=[item], mappings=[mapping], sources=[source], rates=[user_rate()])

    assert result.status == "resolved"
    assert result.rate_source == "global_catalog"
    assert result.labor_avg == 0.7


def test_user_rate_is_reused_without_floor_or_stage_in_key():
    result = select(
        rates=[user_rate()],
        applicability={
            "project_variant_id": "variant-a",
            "floor_number": 5,
            "template_stage_number": "2.6.10",
        },
    )

    assert result.status == "resolved"
    assert result.rate_source == "user_catalog"
    assert result.user_rate_id == "user-rate-1"
    assert result.labor_avg == 0.85


def test_user_rate_does_not_cross_units():
    result = select(rates=[user_rate()], unit="m3")

    assert result.status == "needs_user_rate"
    assert result.rate_source is None
    assert result.requires_user_input is True


def test_user_rate_does_not_cross_scope():
    result = select(rates=[user_rate()], scope="external_wall")

    assert result.status == "needs_user_rate"
    assert result.requires_user_input is True


def test_package_requests_decomposition_instead_of_personal_rate():
    selector = WorkRateSelectionService({"wall_package": {"included_operations": ["wall_plastering"]}})
    result = selector.select_rate(
        taxonomy_code="finishing/wall_plastering",
        operation_code="wall_package",
        object_scope_code="internal_wall",
        rate_context_code=None,
        quantity=100,
        unit_code="m2",
        work_name="Комплексная отделка стен",
        items=[],
        mappings=[],
        sources=[],
        user_id="user-1",
        user_rates=[],
    )

    assert result.status == "needs_decomposition"
    assert result.review_reason == "atomic_work_required"


def test_apply_user_rate_calculates_labor_and_snapshot():
    from app.services.work_rate_ktp_integration import apply_rate_to_raw_data

    selection = select(rates=[user_rate()])
    raw = apply_rate_to_raw_data(
        {"row_role": "work"},
        selection=selection,
        rate_item=None,
        quantity=100,
        quantity_unit="m2",
        labor_source_mode="rate_catalog",
        work_name="Штукатурка внутренних стен",
    )

    assert raw["rate_source"] == "user_catalog"
    assert raw["selected_user_rate_id"] == "user-rate-1"
    assert raw["calculated_labor_hours"] == 85.0
    assert raw["resolved_labor_hours"] == 85.0
    assert raw["applied_labor_hours_per_unit"] == 0.85


def test_missing_rate_builds_single_unit_input_request():
    from app.services.work_rate_ktp_integration import apply_rate_to_raw_data

    selection = select(rates=[])
    raw = apply_rate_to_raw_data(
        {"row_role": "work"},
        selection=selection,
        rate_item=None,
        quantity=100,
        quantity_unit="m2",
        labor_source_mode="rate_catalog",
        work_name="Штукатурка внутренних стен",
    )

    request = raw["user_rate_input_request"]
    assert raw["rate_status"] == "needs_user_rate"
    assert request["unit_code"] == "m2"
    assert request["labor_unit"] == "person_hour"
    assert "accepted_input_units" not in request


def test_user_rate_does_not_cross_rate_context():
    exterior = user_rate(
        operation_code="brick_masonry",
        taxonomy_code="walls/brick_masonry",
        object_scope_code="external_wall",
        rate_context_code="exterior_wall",
    )
    result = WorkRateSelectionService().select_rate(
        taxonomy_code="walls/brick_masonry",
        operation_code="brick_masonry",
        object_scope_code="external_wall",
        rate_context_code="interior_wall",
        quantity=10,
        unit_code="m3",
        work_name="Кладка внутренних кирпичных стен",
        items=[],
        mappings=[],
        sources=[],
        user_id="user-1",
        user_rates=[exterior],
    )

    assert result.status == "needs_user_rate"
    assert result.requires_user_input is True


def test_global_other_unit_falls_back_to_user_rate_in_row_unit():
    source = WorkRateSource(id="source-1", source_kind=SOURCE_NORMATIVE)
    item = WorkRateItem(
        id="global-m3",
        source_id=source.id,
        name="Штукатурка по объёму",
        unit_code="m3",
        labor_min=1.2,
        labor_avg=1.2,
        labor_max=1.2,
        labor_basis="normative",
        has_active_mapping=True,
        auto_applicable=True,
    )
    mapping = WorkRateMapping(
        id="mapping-m3",
        rate_item_id=item.id,
        taxonomy_code="finishing/wall_plastering",
        operation_code="wall_plastering",
        object_scope_code="internal_wall",
        rate_context_code=None,
        mapping_mode=MAPPING_DIRECT,
        confidence=1.0,
    )

    result = select(
        items=[item],
        mappings=[mapping],
        sources=[source],
        rates=[user_rate()],
        unit="m2",
    )

    assert result.status == "resolved"
    assert result.rate_source == "user_catalog"
    assert result.unit_code == "m2"


def test_user_rate_does_not_cross_insulation_variant():
    mineral = user_rate(
        taxonomy_code="insulation/thermal_insulation",
        operation_code="thermal_insulation",
        object_scope_code="external_wall",
        rate_variant_code="facade_mineral_wool",
    )
    selector = WorkRateSelectionService()
    result = selector.select_rate(
        taxonomy_code="insulation/thermal_insulation",
        operation_code="thermal_insulation",
        object_scope_code="external_wall",
        rate_context_code=None,
        quantity=100,
        unit_code="m2",
        work_name="Утепление фасада плитами XPS",
        items=[],
        mappings=[],
        sources=[],
        user_id="user-1",
        user_rates=[mineral],
    )

    assert result.status == "needs_user_rate"
    assert result.rate_variant_code == "facade_xps"


def test_insulation_requires_material_and_location_before_user_rate():
    selector = WorkRateSelectionService()
    result = selector.select_rate(
        taxonomy_code="insulation/thermal_insulation",
        operation_code="thermal_insulation",
        object_scope_code="external_wall",
        rate_context_code=None,
        quantity=100,
        unit_code="m2",
        work_name="Устройство теплоизоляции",
        items=[],
        mappings=[],
        sources=[],
        user_id="user-1",
        user_rates=[],
    )

    assert result.status == "needs_clarification"
    assert result.review_reason in {"rate_variant_required", "insulation_context_not_resolved"}


def test_gantt_does_not_double_multiply_catalog_total():
    from types import SimpleNamespace

    estimate = SimpleNamespace(
        id="estimate-1",
        labor_hours=None,
        quantity=100,
        raw_data={"resolved_labor_hours": 85.0},
        work_name="Штукатурка",
        total_price=None,
        fer_table_id=None,
        fer_multiplier=1,
    )

    assert GanttBuilder()._calc_labor_hours(estimate, 1, 8.0, {}) == 85.0


def test_generic_global_insulation_rate_can_apply_without_personal_variant():
    source = WorkRateSource(id="source-insulation", source_kind=SOURCE_NORMATIVE)
    item = WorkRateItem(
        id="global-insulation",
        source_id=source.id,
        name="Теплоизоляция",
        unit_code="m2",
        labor_min=0.4,
        labor_avg=0.4,
        labor_max=0.4,
        labor_basis="normative",
        has_active_mapping=True,
        auto_applicable=True,
    )
    mapping = WorkRateMapping(
        id="mapping-insulation",
        rate_item_id=item.id,
        taxonomy_code="insulation/thermal_insulation",
        operation_code="thermal_insulation",
        object_scope_code="external_wall",
        rate_context_code=None,
        mapping_mode=MAPPING_DIRECT,
        confidence=1.0,
    )
    result = WorkRateSelectionService().select_rate(
        taxonomy_code="insulation/thermal_insulation",
        operation_code="thermal_insulation",
        object_scope_code="external_wall",
        rate_context_code=None,
        quantity=100,
        unit_code="m2",
        work_name="Устройство теплоизоляции",
        items=[item],
        mappings=[mapping],
        sources=[source],
        user_id="user-1",
        user_rates=[],
    )

    assert result.status == "resolved"
    assert result.rate_source == "global_catalog"


def test_explicit_object_scope_requirement_blocks_personal_rate_without_scope():
    result = WorkRateSelectionService().select_rate(
        taxonomy_code="foundation/foundation_preparation_layers",
        operation_code="sand_backfill",
        object_scope_code=None,
        rate_context_code=None,
        quantity=10,
        unit_code="m3",
        work_name="Отсыпка песком",
        items=[],
        mappings=[],
        sources=[],
        user_id="user-1",
        user_rates=[],
        applicability={"object_scope_required": True},
    )

    assert result.status == "needs_clarification"
    assert result.review_reason == "object_scope_required"


def test_empty_global_catalog_still_applies_personal_rate(monkeypatch, tmp_path):
    import app.services.upload_service as upload_service
    import app.services.work_taxonomy_service as taxonomy_service
    from types import SimpleNamespace

    monkeypatch.setenv("WORK_RATE_CATALOG_FILE", str(tmp_path / "missing-catalog.json"))
    monkeypatch.setattr(
        taxonomy_service,
        "DICTIONARY_FILE",
        str((__import__("pathlib").Path("app/data/construction_work_dictionary_v6_5_1.json")).resolve()),
    )
    row = SimpleNamespace(
        id="row-1",
        section="Отделка",
        work_name="Штукатурка внутренних стен",
        unit="м2",
        quantity=100,
        labor_hours=None,
        raw_data={
            "row_role": "work",
            "work_type_applicable": True,
            "work_subtype_code": "finishing/wall_plastering",
            "operation_code": "wall_plastering",
            "selected_object_scope_code": "internal_wall",
        },
    )
    upload_service._enrich_work_rates_sync(
        [row],
        {
            "user_id": "user-1",
            "labor_source_mode": "rate_catalog",
            "user_work_rates": [user_rate().as_dict()],
        },
        project_id="project-1",
    )

    assert row.raw_data["rate_status"] == "resolved"
    assert row.raw_data["rate_source"] == "user_catalog"
    assert row.raw_data["calculated_labor_hours"] == 85.0
    assert row.labor_hours is None


def test_preview_materialization_calls_rate_enrichment(monkeypatch):
    from types import SimpleNamespace
    import app.services.estimate_import_worker as worker
    import app.services.upload_service as upload_service

    captured = {}
    monkeypatch.setattr(worker, "_ensure_stage10_building_params", lambda batch, rows: None)
    monkeypatch.setattr(worker, "_apply_stage10_text_overrides", lambda rows, batch, stages=None: None)
    monkeypatch.setattr(upload_service, "_enrich_work_subtypes_sync", lambda rows, hierarchy: {})
    monkeypatch.setattr(
        upload_service,
        "_enrich_work_stages_sync",
        lambda rows, hierarchy, preclassified, building_params: None,
    )

    def fake_rate_enrichment(rows, hierarchy, *, project_id=None):
        captured["rows"] = rows
        captured["hierarchy"] = dict(hierarchy)
        captured["project_id"] = project_id
        for row in rows:
            row.raw_data["rate_status"] = "needs_user_rate"

    monkeypatch.setattr(upload_service, "_enrich_work_rates_sync", fake_rate_enrichment)
    batch = SimpleNamespace(
        taxonomy_snapshot={},
        estimate_kind=1,
        estimate_type_id="type-1",
        estimate_type_title="Type",
        estimate_type_number="1",
        project_variant_id="variant-1",
        project_variant_title="Variant",
        project_variant_number="1",
        taxonomy_dictionary_version="v1",
        rate_owner_user_id="user-1",
        project_id="project-1",
        building_params={},
    )
    rows = worker._prepare_stage10_rows_for_materialization(
        [
            {
                "source_row_key": "row-key-1",
                "source_text": "Штукатурка стен",
                "parsed_data": {
                    "work_name": "Штукатурка стен",
                    "unit": "м2",
                    "quantity": 10,
                    "raw_data": {"row_role": "work"},
                },
                "classification_result": {
                    "row_role": "work",
                    "work_subtype_code": "finishing/wall_plastering",
                    "operation_code": "wall_plastering",
                },
            }
        ],
        batch,
        user_work_rates=[user_rate().as_dict()],
    )

    assert rows[0].raw_data["rate_status"] == "needs_user_rate"
    assert captured["project_id"] == "project-1"
    assert captured["hierarchy"]["user_id"] == "user-1"
    assert captured["hierarchy"]["user_work_rates"][0]["id"] == "user-rate-1"


def test_save_endpoint_does_not_mutate_when_global_rate_exists(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4
    from fastapi import HTTPException
    import app.api.routes.user_work_rates as route
    from app.services.work_rate_models import RateSelectionResult

    project_id = uuid4()
    batch_id = uuid4()
    row_id = uuid4()
    owner_id = str(uuid4())
    original_raw = {"rate_status": "needs_user_rate"}
    row = SimpleNamespace(id=str(row_id), raw_data=dict(original_raw), labor_hours=Decimal("0.5"))
    batch = SimpleNamespace(rate_owner_user_id=owner_id)

    async def owned(*args, **kwargs):
        return batch, row

    monkeypatch.setattr(route, "_estimate_row_in_project", owned)
    monkeypatch.setattr(route, "_catalog", lambda path: object())
    monkeypatch.setattr(
        route,
        "_select_for_row",
        lambda **kwargs: (
            RateSelectionResult(
                status="resolved",
                rate_source="global_catalog",
                taxonomy_code="finishing/wall_plastering",
                operation_code="wall_plastering",
                object_scope_code="internal_wall",
                unit_code="m2",
            ),
            None,
            "m2",
        ),
    )

    class FakeDb:
        commits = 0
        rollbacks = 0

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    db = FakeDb()
    try:
        asyncio.run(
            route.save_user_rate_from_estimate_row(
                project_id=project_id,
                estimate_batch_id=batch_id,
                row_id=row_id,
                body=route.SaveUserRateRequest(labor_hours_per_unit=Decimal("0.85")),
                _member=SimpleNamespace(role="owner"),
                current_user=SimpleNamespace(id=owner_id),
                db=db,
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "global_rate_already_available"
    else:
        raise AssertionError("global rate must block personal upsert")

    assert db.commits == 0
    assert db.rollbacks == 0
    assert row.raw_data == original_raw
    assert row.labor_hours == Decimal("0.5")


def test_save_endpoint_applies_personal_rate_without_overwriting_manual_norm(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4
    import app.api.routes.user_work_rates as route
    from app.services.work_rate_models import RateSelectionResult

    project_id = uuid4()
    batch_id = uuid4()
    row_id = uuid4()
    owner_id = str(uuid4())
    row = SimpleNamespace(
        id=str(row_id),
        raw_data={"rate_status": "needs_user_rate"},
        labor_hours=Decimal("0.5"),
        work_name="Штукатурка стен",
        dictionary_version="v1",
    )
    batch = SimpleNamespace(rate_owner_user_id=owner_id)
    record = user_rate(id=str(uuid4()), user_id=owner_id)

    async def owned(*args, **kwargs):
        return batch, row

    monkeypatch.setattr(route, "_estimate_row_in_project", owned)
    monkeypatch.setattr(route, "_catalog", lambda path: object())

    def select_for_row(*, user_rates, **kwargs):
        if not user_rates:
            return (
                RateSelectionResult(
                    status="needs_user_rate",
                    taxonomy_code=record.taxonomy_code,
                    operation_code=record.operation_code,
                    object_scope_code=record.object_scope_code,
                    rate_context_code=record.rate_context_code,
                    rate_variant_code=record.rate_variant_code,
                    unit_code=record.unit_code,
                    requires_user_input=True,
                    review_reason="user_rate_input_required",
                ),
                None,
                record.unit_code,
            )
        return (
            RateSelectionResult(
                status="resolved",
                rate_source="user_catalog",
                taxonomy_code=record.taxonomy_code,
                operation_code=record.operation_code,
                object_scope_code=record.object_scope_code,
                rate_context_code=record.rate_context_code,
                rate_variant_code=record.rate_variant_code,
                unit_code=record.unit_code,
                user_rate_id=record.id,
                user_rate_owner_id=owner_id,
                labor_avg=float(record.labor_hours_per_unit),
                labor_min=float(record.labor_hours_per_unit),
                labor_max=float(record.labor_hours_per_unit),
                rate_auto_applicable=True,
            ),
            None,
            record.unit_code,
        )

    monkeypatch.setattr(route, "_select_for_row", select_for_row)

    class FakeRepository:
        async def upsert(self, db, **kwargs):
            return record

        async def list_records(self, db, **kwargs):
            return [record]

    monkeypatch.setattr(route, "UserWorkRateRepository", FakeRepository)

    def apply_selection(*, row, **kwargs):
        row.raw_data = {
            **row.raw_data,
            "rate_status": "resolved",
            "rate_source": "user_catalog",
            "selected_user_rate_id": record.id,
            "calculated_labor_hours": 85.0,
            "resolved_labor_hours": 50.0,
        }
        return row.raw_data

    monkeypatch.setattr(route, "_apply_selection_to_row", apply_selection)

    class FakeDb:
        commits = 0
        rollbacks = 0

        async def scalars(self, statement):
            return [row]

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    db = FakeDb()
    result = asyncio.run(
        route.save_user_rate_from_estimate_row(
            project_id=project_id,
            estimate_batch_id=batch_id,
            row_id=row_id,
            body=route.SaveUserRateRequest(labor_hours_per_unit=Decimal("0.85")),
            _member=SimpleNamespace(role="owner"),
            current_user=SimpleNamespace(id=owner_id),
            db=db,
        )
    )

    assert db.commits == 1
    assert db.rollbacks == 0
    assert result["recalculation"] == {"matched_rows": 1, "updated_rows": 1}
    assert row.raw_data["selected_user_rate_id"] == record.id
    # Existing Estimate.labor_hours remains the manual per-unit norm. The
    # catalogue total is persisted only in raw_data snapshots.
    assert row.labor_hours == Decimal("0.5")


def test_save_endpoint_rejects_non_owner_catalog_user(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4
    from fastapi import HTTPException
    import app.api.routes.user_work_rates as route

    project_id = uuid4()
    batch_id = uuid4()
    row_id = uuid4()
    owner_id = str(uuid4())
    other_user_id = str(uuid4())
    batch = SimpleNamespace(rate_owner_user_id=owner_id)
    row = SimpleNamespace(id=str(row_id), raw_data={}, labor_hours=None)

    async def owned(*args, **kwargs):
        return batch, row

    monkeypatch.setattr(route, "_estimate_row_in_project", owned)

    class FakeDb:
        commits = 0
        rollbacks = 0

    db = FakeDb()
    try:
        asyncio.run(
            route.save_user_rate_from_estimate_row(
                project_id=project_id,
                estimate_batch_id=batch_id,
                row_id=row_id,
                body=route.SaveUserRateRequest(labor_hours_per_unit=Decimal("0.85")),
                _member=SimpleNamespace(role="pm"),
                current_user=SimpleNamespace(id=other_user_id),
                db=db,
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "rate_catalog_owner_required"
    else:
        raise AssertionError("non-owner must not write a shared estimate rate")


def test_subtype_output_fallback_keeps_fractional_labor_hours():
    resolved = WorkRateSelectionService.resolve_labor_source(
        labor_source_mode="rate_catalog",
        subtype_output_per_day=100,
        quantity=101,
        crew_size=5,
        hours_per_day=8,
    )

    assert resolved.resolved_labor_source == "subtype_output_per_day"
    assert resolved.resolved_labor_hours == 40.4
    assert WorkRateSelectionService.calculate_duration(
        resolved.resolved_labor_hours,
        crew_size=5,
        hours_per_day=8,
    ) == 2


def test_duration_calculations_share_validation_contract():
    invalid_cases = [
        (None, 5, 8),
        (0, 5, 8),
        (-1, 5, 8),
        (40, None, 8),
        (40, 0, 8),
        (40, 5, 0),
    ]
    for labor, crew, hours in invalid_cases:
        assert calculate_working_days(labor, crew, hours) is None
        assert WorkRateSelectionService.calculate_duration(
            labor,
            crew_size=crew,
            hours_per_day=hours,
        ) is None

    assert calculate_working_days(40.4, 5, 8) == 2
    assert WorkRateSelectionService.calculate_duration(
        40.4,
        crew_size=5,
        hours_per_day=8,
    ) == 2


def test_stale_catalog_output_resets_to_current_default():
    from types import SimpleNamespace
    from app.services.ktp_estimate_service import _sync_automatic_output_per_day

    row = SimpleNamespace(output_per_day=12.5, output_source="catalog")
    _sync_automatic_output_per_day(
        row,
        catalog_output_per_day=None,
        default_output_per_day=7.0,
    )

    assert row.output_per_day == 7.0
    assert row.output_source == "default"


def test_catalog_output_resets_to_empty_default_when_subtype_has_no_default():
    from types import SimpleNamespace
    from app.services.ktp_estimate_service import _sync_automatic_output_per_day

    row = SimpleNamespace(output_per_day=12.5, output_source="catalog")
    _sync_automatic_output_per_day(
        row,
        catalog_output_per_day=None,
        default_output_per_day=None,
    )

    assert row.output_per_day is None
    assert row.output_source == "default"


def test_manual_output_is_never_overwritten_by_catalog_refresh():
    from types import SimpleNamespace
    from app.services.ktp_estimate_service import _sync_automatic_output_per_day

    row = SimpleNamespace(output_per_day=15.0, output_source="manual")
    _sync_automatic_output_per_day(
        row,
        catalog_output_per_day=20.0,
        default_output_per_day=7.0,
    )

    assert row.output_per_day == 15.0
    assert row.output_source == "manual"
