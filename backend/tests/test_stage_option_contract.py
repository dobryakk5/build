from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import DBAPIError

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.floor_structure_service import build_stage_instances, validate_building_params
from app.services.estimate_import_worker import (
    DATABASE_IMPORT_FAILURE,
    GENERIC_IMPORT_FAILURE,
    _apply_confirmed_stage_options,
    _exception_reason_code,
)
from app.models import KtpEstimateSession
from app.services.ktp_estimate_service import _materialize_wbs
from app.services.semantic_options_service import (
    PROJECTION_GENERATION_STATUS_VALUES,
    StageOptionValidationError,
    generate_semantic_operation_projections,
    resolve_semantic_options,
    validate_required_stage_options,
)
from app.services.work_taxonomy_service import get_project_variant_definition


ESTIMATE_TYPE = "residential_construction"
VARIANT_ID = "residential_construction_kirpichnye_doma"
FOUNDATION = "residential_construction.fundamentnye_raboty"
HIGH_BASEMENT = "residential_construction.vysokiy_cokol"
BASEMENT_SLAB = "residential_construction.ustroystvo_perekrytiy_cokolya"
LINTEL = "residential_construction.ustroystvo_peremychek_nad_proemami_kladki_etazha"
FLOOR_SLAB = "residential_construction.ustroystvo_perekrytiy_etazha"
PARTITIONS = "residential_construction.ustroystvo_vnutrennih_peregorodok_etazha"
FACADE = "residential_construction.naruzhnaya_fasadnaya_otdelka"


def context(*, basement: bool = False, mansard: bool = False):
    variant = get_project_variant_definition(ESTIMATE_TYPE, VARIANT_ID)
    building = {"floors_count": 1, "has_basement": basement, "has_mansard": mansard}
    stages = build_stage_instances(variant, validate_building_params(building, variant))
    return variant, building, stages


def options(*, basement: bool = False, floor_slab: bool = True, facade: str = "facing_brick"):
    result = {
        FOUNDATION: "usp",
        LINTEL: "metal",
        PARTITIONS: "block",
        FACADE: facade,
    }
    if floor_slab:
        result[FLOOR_SLAB] = "monolithic_rc"
    if basement:
        result[HIGH_BASEMENT] = "brick"
        result[BASEMENT_SLAB] = "slab_on_grade"
    return result


def test_dictionary_required_branches_are_selectable_one():
    variant, _building, _stages = context()
    required_ids = {FOUNDATION, HIGH_BASEMENT, BASEMENT_SLAB, LINTEL, FLOOR_SLAB, PARTITIONS, FACADE}
    stages = {stage["canonical_stage_id"]: stage for stage in variant["stages"]}
    for stage_id in required_ids:
        stage = stages[stage_id]
        assert stage["stage_options_mode"] == "selectable_one"
        assert stage["stage_options_policy"]["min_selected"] == 1
        assert stage["stage_options_policy"]["max_selected"] == 1


def test_resolver_synchronizes_singular_and_plural_fields():
    variant, building, stages = context()
    normalized = validate_required_stage_options(
        variant=variant,
        stage_instances=stages,
        building_params=building,
        submitted_project_structure_options=options(),
    ).normalized_options
    report = resolve_semantic_options(variant, stages, project_structure_options=normalized)
    assert report.valid
    for stage in stages:
        if stage.get("stage_options_mode") == "selectable_one":
            assert stage["semantic_stage_option_ids"] == [stage["semantic_stage_option_id"]]


def test_no_finish_is_valid_not_applicable_state():
    variant, building, stages = context()
    selected = options(facade="no_finish")
    validate_required_stage_options(
        variant=variant,
        stage_instances=stages,
        building_params=building,
        submitted_project_structure_options=selected,
    )
    assert resolve_semantic_options(variant, stages, project_structure_options=selected).valid
    generate_semantic_operation_projections(variant, stages)
    facade = next(stage for stage in stages if stage["canonical_stage_id"] == FACADE)
    assert facade["execution_applicability"] == "not_applicable"
    assert facade["projection_generation_status"] == "skipped_not_applicable"
    assert facade["operation_projections"] == []
    assert "skipped_not_applicable" in PROJECTION_GENERATION_STATUS_VALUES


def test_multiple_values_are_rejected_even_for_single_item_array():
    variant, building, stages = context()
    selected = options()
    selected[FOUNDATION] = ["usp"]
    with pytest.raises(StageOptionValidationError) as exc:
        validate_required_stage_options(
            variant=variant,
            stage_instances=stages,
            building_params=building,
            submitted_project_structure_options=selected,
        )
    assert exc.value.code == "too_many_stage_options_selected"


def test_import_row_inherits_selected_option_and_detected_conflict_is_review_only():
    variant, _building, stages = context()
    selected = options()
    assert resolve_semantic_options(variant, stages, project_structure_options=selected).valid
    foundation_stage = next(stage for stage in stages if stage["canonical_stage_id"] == FOUNDATION)
    generic = SimpleNamespace(raw_data={
        "row_role": "work",
        "canonical_stage_id": FOUNDATION,
        "stage_instance_id": foundation_stage["stage_instance_id"],
    })
    conflict = SimpleNamespace(raw_data={
        "row_role": "work",
        "canonical_stage_id": FOUNDATION,
        "stage_instance_id": foundation_stage["stage_instance_id"],
        "semantic_stage_option_id": "pile_grillage",
    })
    _apply_confirmed_stage_options([generic, conflict], variant=variant, resolved_stages=stages)
    assert generic.raw_data["semantic_stage_option_id"] == "usp"
    assert generic.raw_data["stage_option_conflict"] is False
    assert conflict.raw_data["semantic_stage_option_id"] == "usp"
    assert conflict.raw_data["detected_semantic_stage_option_id"] == "pile_grillage"
    assert conflict.raw_data["review_reason"] == "stage_option_conflicts_with_project_selection"
    assert conflict.raw_data["calculation_blocked"] is True


def test_no_finish_does_not_materialize_working_group():
    session = KtpEstimateSession(
        id="00000000-0000-0000-0000-000000000101",
        project_id="00000000-0000-0000-0000-000000000102",
        estimate_batch_id="00000000-0000-0000-0000-000000000103",
        status="stage1_pending",
    )
    groups, items, _warnings = _materialize_wbs(
        session,
        [{
            "title": "Наружная фасадная отделка",
            "sort_order": 16000,
            "sequence_mode": "locked",
            "stage_instance_id": "stage:facade",
            "template_stage_number": "2.7.16",
            "stage_number": "2.7.16",
            "canonical_stage_id": FACADE,
            "semantic_stage_option_id": "no_finish",
            "semantic_stage_option_title": "Без отделки",
            "stage_option_source": "project_structure_options",
            "execution_applicability": "not_applicable",
            "items": [],
        }],
        {},
    )
    assert items == []
    assert groups == []


def test_import_failure_reason_is_stable_and_fits_database_column():
    class DomainFailure(RuntimeError):
        reason_code = "domain_failure"

    assert _exception_reason_code(DomainFailure("verbose details")) == "domain_failure"
    assert _exception_reason_code(RuntimeError("preview_rows_missing")) == "preview_rows_missing"
    assert _exception_reason_code(RuntimeError("x" * 500)) == GENERIC_IMPORT_FAILURE
    db_error = DBAPIError("INSERT", {}, RuntimeError("value too long"))
    assert _exception_reason_code(db_error) == DATABASE_IMPORT_FAILURE
    assert len(_exception_reason_code(RuntimeError("x" * 500))) <= 128


def test_projection_status_storage_fits_longest_contract_value():
    from app.models import EstimateBatch, StageInstanceProjectionSummary
    from app.services.semantic_options_service import PROJECTION_GENERATION_STATUS_VALUES

    longest = max(map(len, PROJECTION_GENERATION_STATUS_VALUES))
    assert StageInstanceProjectionSummary.__table__.c.projection_generation_status.type.length >= longest
    assert EstimateBatch.__table__.c.projection_generation_status.type.length >= longest
