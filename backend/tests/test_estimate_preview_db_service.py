from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.estimate_preview_db_service import PreviewDomainError, _validate_stage10_preview_metadata
from app.services.floor_structure_service import build_stage_instances, validate_building_params
from app.services.semantic_options_service import validate_required_stage_options
from app.services.work_taxonomy_service import get_project_variant_definition


ESTIMATE_TYPE_ID = "residential_construction"
VARIANT_ID = "residential_construction_kirpichnye_doma"
FOUNDATION = "residential_construction.fundamentnye_raboty"
HIGH_BASEMENT = "residential_construction.vysokiy_cokol"
BASEMENT_SLAB = "residential_construction.ustroystvo_perekrytiy_cokolya"
LINTEL = "residential_construction.ustroystvo_peremychek_nad_proemami_kladki_etazha"
FLOOR_SLAB = "residential_construction.ustroystvo_perekrytiy_etazha"
PARTITIONS = "residential_construction.ustroystvo_vnutrennih_peregorodok_etazha"
FACADE = "residential_construction.naruzhnaya_fasadnaya_otdelka"


def required_options(*, basement: bool = False, floor_slab: bool = True) -> dict[str, str]:
    result = {
        FOUNDATION: "usp",
        LINTEL: "metal",
        PARTITIONS: "block",
        FACADE: "facing_brick",
    }
    if floor_slab:
        result[FLOOR_SLAB] = "monolithic_rc"
    if basement:
        result[HIGH_BASEMENT] = "brick"
        result[BASEMENT_SLAB] = "precast_rc"
    return result


def validate(params: dict, options: dict):
    return _validate_stage10_preview_metadata(
        estimate_type_id=ESTIMATE_TYPE_ID,
        project_variant_id=VARIANT_ID,
        building_params=params,
        project_structure_options=options,
    )


def test_preview_returns_all_missing_required_options():
    with pytest.raises(PreviewDomainError) as exc:
        validate({"floors_count": 2, "has_basement": True, "has_mansard": False}, {})
    assert exc.value.code == "stage_option_required"
    assert len(exc.value.details["missing"]) == 7


def test_preview_accepts_complete_building_scope_selection():
    params = {"floors_count": 2, "has_basement": True, "has_mansard": False}
    building, options = validate(params, required_options(basement=True))
    assert building == params
    assert options == required_options(basement=True)


def test_preview_rejects_single_item_legacy_array():
    options = required_options(basement=True)
    options[BASEMENT_SLAB] = ["monolithic_rc"]
    with pytest.raises(PreviewDomainError) as exc:
        validate({"floors_count": 2, "has_basement": True, "has_mansard": False}, options)
    assert exc.value.code == "too_many_stage_options_selected"


def test_preview_rejects_explicit_not_applicable_basement_option():
    options = required_options()
    options[HIGH_BASEMENT] = "brick"
    with pytest.raises(PreviewDomainError) as exc:
        validate({"floors_count": 1, "has_basement": False, "has_mansard": False}, options)
    assert exc.value.code == "stage_option_not_applicable"


def test_preview_drops_inherited_not_applicable_draft_option():
    variant = get_project_variant_definition(ESTIMATE_TYPE_ID, VARIANT_ID)
    building = {"floors_count": 1, "has_basement": False, "has_mansard": False}
    params = validate_building_params(building, variant)
    result = validate_required_stage_options(
        variant=variant,
        stage_instances=build_stage_instances(variant, params),
        building_params=building,
        submitted_project_structure_options=required_options(),
        inherited_draft_options={HIGH_BASEMENT: "brick", BASEMENT_SLAB: "precast_rc"},
    )
    assert {item["canonical_stage_id"] for item in result.dropped_stage_options} == {
        HIGH_BASEMENT,
        BASEMENT_SLAB,
    }


def test_preview_does_not_require_floor_slab_without_instance():
    building = {"floors_count": 1, "has_basement": False, "has_mansard": True}
    _params, options = validate(building, required_options(floor_slab=False))
    assert FLOOR_SLAB not in options


def test_preview_accepts_no_finish():
    options = required_options()
    options[FACADE] = "no_finish"
    _params, normalized = validate(
        {"floors_count": 1, "has_basement": False, "has_mansard": False}, options
    )
    assert normalized[FACADE] == "no_finish"
