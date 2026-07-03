from __future__ import annotations

import inspect
import os
from datetime import timezone
from types import SimpleNamespace

import pytest
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:secret@localhost:5432/construction"
)

from app.core.config import settings
from app.core.time import utc_now
from app.models import Estimate, EstimateBatch, KtpEstimateSession, KtpWbsItem
from app.services.ktp_errors import (
    InvalidStageAwareRowReference,
    Stage1ReviewRequired,
    TaxonomySnapshotIntegrity,
    TaxonomySnapshotRequired,
)
from app.services.ktp_estimate_service import (
    GROUPING_MODE_STAGE_AWARE,
    _build_stage_aware_groups,
    _attach_stage_review_metadata,
    _format_estimate_rows_for_prompt,
    _materialize_wbs,
    _process_stage1,
    _sort_stage_groups,
    _stage_instances_from_batch_snapshot,
    compute_item_review_state,
    get_session,
    get_wbs,
    start_stage1_job,
)
from app.services.taxonomy_snapshot_service import build_immutable_taxonomy_snapshot
from app.services.taxonomy_snapshot_service import load_immutable_taxonomy_snapshot


PROJECT_ID = "00000000-0000-0000-0000-000000000002"
BATCH_ID = "00000000-0000-0000-0000-000000000001"


def make_batch(*, with_snapshot: bool = True) -> EstimateBatch:
    snapshot = (
        build_immutable_taxonomy_snapshot(
            project_variant_id="residential_construction_kirpichnye_doma"
        ).to_json()
        if with_snapshot
        else None
    )
    return EstimateBatch(
        id=BATCH_ID,
        project_id=PROJECT_ID,
        rate_owner_user_id="00000000-0000-0000-0000-000000000003",
        name="brick test",
        estimate_kind=2,
        estimate_type_id="residential_construction",
        project_variant_id="residential_construction_kirpichnye_doma",
        taxonomy_snapshot=snapshot,
        building_params={
            "floors_count": 3,
            "has_basement": True,
            "has_mansard": True,
        },
        project_structure_options={
            "residential_construction.fundamentnye_raboty": "usp",
            "residential_construction.vysokiy_cokol": "brick",
            "residential_construction.ustroystvo_perekrytiy_cokolya": "precast_rc",
            "residential_construction.ustroystvo_peremychek_nad_proemami_kladki_etazha": "metal",
            "residential_construction.ustroystvo_perekrytiy_etazha": "monolithic_rc",
            "residential_construction.ustroystvo_vnutrennih_peregorodok_etazha": "block",
            "residential_construction.naruzhnaya_fasadnaya_otdelka": "facing_brick",
        },
    )


def test_dynamic_stage_aware_uses_batch_snapshot() -> None:
    batch = make_batch()
    stages, source, _snapshot = _stage_instances_from_batch_snapshot(batch)
    assert source == "batch_snapshot_dynamic"
    assert len(stages) == 21
    assert not any(
        stage.get("floor_number") == 0
        and stage.get("template_stage_number") in {"2.7.9", "2.7.11"}
        for stage in stages
    )
    assert not any(
        stage.get("floor_number") == 0
        and stage.get("template_stage_number") == "2.7.8"
        for stage in stages
    )


def test_stage_groups_sort_by_floor_then_template_number() -> None:
    groups = [
        SimpleNamespace(
            id="floor1-stage2",
            title="2.7.2. Фундамент",
            floor_number=1,
            template_stage_number="2.7.2",
            stage_number="2.7.F1.20",
            sort_order=10,
        ),
        SimpleNamespace(
            id="basement-stage3",
            title="2.7.3. Цоколь",
            floor_number=0,
            template_stage_number="2.7.3",
            stage_number="2.7.B1.30",
            sort_order=30,
        ),
        SimpleNamespace(
            id="floor1-stage1",
            title="2.7.1. Подготовка",
            floor_number=1,
            template_stage_number="2.7.1",
            stage_number="2.7.F1.10",
            sort_order=20,
        ),
        SimpleNamespace(
            id="fallback",
            title="Нераспределённые работы",
            floor_number=None,
            template_stage_number=None,
            stage_number=None,
            sort_order=1,
        ),
    ]

    assert [group.id for group in _sort_stage_groups(groups)] == [
        "basement-stage3",
        "floor1-stage1",
        "floor1-stage2",
        "fallback",
    ]


def test_stage_grouping_reports_real_snapshot_source() -> None:
    batch = make_batch()
    stages, _source, _snapshot = _stage_instances_from_batch_snapshot(batch)
    estimate = Estimate(
        id="00000000-0000-0000-0000-000000000003",
        project_id=PROJECT_ID,
        work_name="Подготовительные работы",
        work_stage_number=stages[0]["number"],
        row_order=1,
    )
    diagnostics: dict = {}
    groups = _build_stage_aware_groups(
        [estimate], {estimate.id: "R001"}, batch, diagnostics
    )
    assert diagnostics["stage_grouping"]["taxonomy_source"] == "batch_snapshot_dynamic"
    assert sum(len(group["items"]) for group in groups) == 1


def test_snapshot_is_required_for_new_27() -> None:
    with pytest.raises(TaxonomySnapshotRequired):
        _stage_instances_from_batch_snapshot(make_batch(with_snapshot=False))


def test_unknown_stage_aware_row_key_is_not_ai_added() -> None:
    session = KtpEstimateSession(
        id="00000000-0000-0000-0000-000000000010",
        project_id=PROJECT_ID,
        estimate_batch_id=BATCH_ID,
        status="stage1_processing",
    )
    diagnostics: dict = {}
    with pytest.raises(InvalidStageAwareRowReference):
        _materialize_wbs(
            session,
            [
                {
                    "title": "Фундамент",
                    "items": [
                        {
                            "name": "Опалубка",
                            "origin": "from_estimate",
                            "row_key": "R999",
                        }
                    ],
                }
            ],
            {},
            diagnostics=diagnostics,
            grouping_mode=GROUPING_MODE_STAGE_AWARE,
        )
    assert diagnostics["invalid_estimate_row_keys"][0]["row_key"] == "R999"


def test_review_state_computation_does_not_mutate_item() -> None:
    estimate = Estimate(
        id="00000000-0000-0000-0000-000000000020",
        project_id=PROJECT_ID,
        work_name="Работа",
        needs_review=True,
        review_reason="stage_low_confidence",
        classification_needs_review=False,
    )
    item = KtpWbsItem(
        id="00000000-0000-0000-0000-000000000021",
        group_id="00000000-0000-0000-0000-000000000022",
        session_id="00000000-0000-0000-0000-000000000023",
        name="Работа",
        origin="from_estimate",
        review_status="accepted",
        operator_review_required=False,
        work_type_needs_review=False,
        manual_override=False,
    )
    state = compute_item_review_state(item, estimate)
    assert state.operator_review_required is True
    assert item.operator_review_required is False


def test_prompt_uses_configured_limit_and_reports_truncation(monkeypatch) -> None:
    monkeypatch.setattr(settings, "KTP_ESTIMATE_CHUNK_ROWS", 2)
    estimates = [
        Estimate(
            id=f"00000000-0000-0000-0000-{index:012d}",
            project_id=PROJECT_ID,
            work_name=f"Работа {index}",
        )
        for index in range(1, 4)
    ]
    rendered = _format_estimate_rows_for_prompt(estimates)
    assert "Работа 1" in rendered
    assert "Работа 2" in rendered
    assert "Работа 3" not in rendered
    assert "не включено 1 строк" in rendered
    assert "контекст неполный" in rendered


def test_stage1_worker_contains_atomic_pending_claim_and_generation_fence() -> None:
    worker_source = inspect.getsource(_process_stage1)
    starter_source = inspect.getsource(start_stage1_job)
    assert '.where(Job.status == "pending")' in worker_source
    assert ".returning(Job.id)" in worker_source
    assert "stage1_generation" in worker_source
    assert ".with_for_update()" in worker_source
    assert "stage1_generation" in starter_source
    assert "Stage1JobAlreadyRunning" in starter_source


def test_utc_now_is_aware() -> None:
    value = utc_now()
    assert value.tzinfo is not None
    assert value.utcoffset() == timezone.utc.utcoffset(value)


def test_typed_error_has_stable_http_contract() -> None:
    error = Stage1ReviewRequired(
        "Нужна проверка", details={"problem_item_ids": ["x"]}
    )
    assert error.http_status == 409
    assert error.code == "stage1_review_required"
    assert error.details["problem_item_ids"] == ["x"]


def test_session_model_has_generation_fence() -> None:
    session = KtpEstimateSession(
        project_id=PROJECT_ID,
        estimate_batch_id=BATCH_ID,
    )
    session.stage1_generation = 4
    assert session.stage1_generation == 4


def test_read_paths_are_side_effect_free() -> None:
    get_session_source = inspect.getsource(get_session)
    get_wbs_source = inspect.getsource(get_wbs)
    attach_source = inspect.getsource(_attach_stage_review_metadata)
    assert "_expire_stale_stage1_session" not in get_session_source
    assert "_expire_stale_stage1_session" not in get_wbs_source
    assert "await db.commit()" not in get_session_source
    assert "await db.commit()" not in get_wbs_source
    assert "item.operator_review_required =" not in attach_source



def test_modified_snapshot_is_rejected() -> None:
    batch = make_batch()
    batch.taxonomy_snapshot["variant"]["title"] = "tampered"
    with pytest.raises(TaxonomySnapshotIntegrity):
        _stage_instances_from_batch_snapshot(batch)


def test_snapshot_loader_tolerates_external_batch_metadata() -> None:
    snapshot = build_immutable_taxonomy_snapshot(
        project_variant_id="residential_construction_kirpichnye_doma"
    ).to_json()
    snapshot["building_params"] = {"floors_count": 2, "has_basement": False}
    snapshot["work_rate_catalog_version"] = "1.2"
    snapshot["work_rate_catalog_hash"] = "legacy-external-metadata"

    loaded = load_immutable_taxonomy_snapshot(snapshot).to_json()

    assert loaded["snapshot_content_hash"] == snapshot["snapshot_content_hash"]
    assert "building_params" not in loaded
    assert "work_rate_catalog_version" not in loaded


def test_duplicate_stage_aware_row_key_fails_invariant() -> None:
    session = KtpEstimateSession(
        id="00000000-0000-0000-0000-000000000030",
        project_id=PROJECT_ID,
        estimate_batch_id=BATCH_ID,
        status="stage1_processing",
    )
    estimate = Estimate(
        id="00000000-0000-0000-0000-000000000031",
        project_id=PROJECT_ID,
        work_name="Опалубка",
    )
    diagnostics: dict = {}
    with pytest.raises(InvalidStageAwareRowReference):
        _materialize_wbs(
            session,
            [{
                "title": "Фундамент",
                "items": [
                    {"name": "Опалубка", "origin": "from_estimate", "row_key": "R001"},
                    {"name": "Опалубка дубль", "origin": "from_estimate", "row_key": "R001"},
                ],
            }],
            {"R001": estimate},
            diagnostics=diagnostics,
            grouping_mode=GROUPING_MODE_STAGE_AWARE,
        )
    assert diagnostics["duplicate_estimate_row_keys"][0]["row_key"] == "R001"
