from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.estimate_preview_db_service import (
    BASEMENT_TOP_SLAB_STAGE_ID,
    PreviewDomainError,
    _validate_stage10_preview_metadata,
)
from app.services.work_taxonomy_service import get_project_variant_definition


ESTIMATE_TYPE_ID = "residential_construction"
VARIANT_ID = "residential_construction_kirpichnye_doma"
HIGH_BASEMENT_STAGE_ID = "residential_construction.vysokiy_cokol"
LINTEL_STAGE_ID = "residential_construction.ustroystvo_peremychek_nad_proemami_kladki_etazha"
FACADE_STAGE_ID = "residential_construction.naruzhnaya_fasadnaya_otdelka"


def test_stage10_preview_metadata_requires_basement_slab_option_when_basement_enabled():
    with pytest.raises(PreviewDomainError) as exc:
        _validate_stage10_preview_metadata(
            estimate_type_id=ESTIMATE_TYPE_ID,
            project_variant_id=VARIANT_ID,
            building_params={"floors_count": 2, "has_basement": True, "has_mansard": False},
            project_structure_options={},
        )

    assert exc.value.code == "basement_top_slab_option_required"


def test_stage10_preview_metadata_accepts_single_basement_slab_radio_option():
    building_params, project_options = _validate_stage10_preview_metadata(
        estimate_type_id=ESTIMATE_TYPE_ID,
        project_variant_id=VARIANT_ID,
        building_params={"floors_count": 2, "has_basement": True, "has_mansard": False},
        project_structure_options={BASEMENT_TOP_SLAB_STAGE_ID: "monolithic_rc"},
    )

    assert building_params == {"floors_count": 2, "has_basement": True, "has_mansard": False}
    assert project_options == {BASEMENT_TOP_SLAB_STAGE_ID: ["monolithic_rc"]}


def test_stage10_preview_metadata_coerces_single_item_legacy_array_to_radio_option():
    _building_params, project_options = _validate_stage10_preview_metadata(
        estimate_type_id=ESTIMATE_TYPE_ID,
        project_variant_id=VARIANT_ID,
        building_params={"floors_count": 2, "has_basement": True, "has_mansard": False},
        project_structure_options={BASEMENT_TOP_SLAB_STAGE_ID: ["monolithic_rc"]},
    )

    assert project_options == {BASEMENT_TOP_SLAB_STAGE_ID: ["monolithic_rc"]}


def test_stage10_preview_metadata_accepts_radio_value_for_legacy_selectable_many_stage():
    _building_params, project_options = _validate_stage10_preview_metadata(
        estimate_type_id=ESTIMATE_TYPE_ID,
        project_variant_id=VARIANT_ID,
        building_params={"floors_count": 2, "has_basement": False, "has_mansard": False},
        project_structure_options={LINTEL_STAGE_ID: "metal"},
    )

    assert project_options == {LINTEL_STAGE_ID: ["metal"]}


def test_stage10_preview_metadata_accepts_no_facade_finish_option():
    variant = get_project_variant_definition(ESTIMATE_TYPE_ID, VARIANT_ID)
    facade_stage = next(
        stage for stage in variant["stages"] if stage["canonical_stage_id"] == FACADE_STAGE_ID
    )
    no_finish = next(option for option in facade_stage["stage_options"] if option["id"] == "no_finish")

    assert no_finish["title"] == "Без отделки"
    assert no_finish["operation_codes"] == []

    _building_params, project_options = _validate_stage10_preview_metadata(
        estimate_type_id=ESTIMATE_TYPE_ID,
        project_variant_id=VARIANT_ID,
        building_params={"floors_count": 1, "has_basement": False, "has_mansard": False},
        project_structure_options={FACADE_STAGE_ID: "no_finish"},
    )

    assert project_options == {FACADE_STAGE_ID: "no_finish"}


def test_stage10_preview_metadata_rejects_multiple_basement_slab_radio_options():
    with pytest.raises(PreviewDomainError) as exc:
        _validate_stage10_preview_metadata(
            estimate_type_id=ESTIMATE_TYPE_ID,
            project_variant_id=VARIANT_ID,
            building_params={"floors_count": 1, "has_basement": True, "has_mansard": False},
            project_structure_options={BASEMENT_TOP_SLAB_STAGE_ID: ["precast_rc", "slab_on_grade"]},
        )

    assert exc.value.code == "too_many_stage_options_selected"


def test_stage10_preview_metadata_does_not_require_basement_slab_without_basement():
    building_params, project_options = _validate_stage10_preview_metadata(
        estimate_type_id=ESTIMATE_TYPE_ID,
        project_variant_id=VARIANT_ID,
        building_params={"floors_count": 1, "has_basement": False, "has_mansard": True},
        project_structure_options={},
    )

    assert building_params == {"floors_count": 1, "has_basement": False, "has_mansard": True}
    assert project_options == {}


def test_stage10_preview_metadata_drops_basement_branch_options_without_basement():
    _building_params, project_options = _validate_stage10_preview_metadata(
        estimate_type_id=ESTIMATE_TYPE_ID,
        project_variant_id=VARIANT_ID,
        building_params={"floors_count": 1, "has_basement": False, "has_mansard": False},
        project_structure_options={
            HIGH_BASEMENT_STAGE_ID: "brick",
            BASEMENT_TOP_SLAB_STAGE_ID: "precast_rc",
        },
    )

    assert project_options == {}
