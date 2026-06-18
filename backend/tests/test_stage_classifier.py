from app.services.stage_classifier import StageClassifier, normalize_row_role
from app.services.work_taxonomy_service import (
    get_project_variant_stages,
    get_sequential_scoring_policy,
)


ESTIMATE_TYPE_ID = "residential_construction"
PROJECT_VARIANT_ID = "residential_construction_doma_iz_peno_ili_gazoblokov"
BRICK_PROJECT_VARIANT_ID = "residential_construction_kirpichnye_doma"


def _classifier() -> tuple[StageClassifier, list[dict]]:
    return (
        StageClassifier(get_sequential_scoring_policy()),
        get_project_variant_stages(ESTIMATE_TYPE_ID, PROJECT_VARIANT_ID),
    )


def _raw(match, row_role: str = "work") -> dict:
    return match.as_raw_data(
        estimate_type_id=ESTIMATE_TYPE_ID,
        estimate_type_number="2",
        project_variant_id=PROJECT_VARIANT_ID,
        project_variant_number="2.6",
        row_role=row_role,
    )


def test_stage_classifier_maps_gas_block_first_and_second_floor() -> None:
    classifier, stages = _classifier()

    first = _raw(
        classifier.classify_row_to_stage(
            "Кладка стен из газоблока 400 мм на клеевой раствор",
            "work",
            stages,
            estimate_profile_id=ESTIMATE_TYPE_ID,
        )
    )
    second = _raw(
        classifier.classify_row_to_stage(
            "Кладка стен 2 этажа из газоблока",
            "work",
            stages,
            estimate_profile_id=ESTIMATE_TYPE_ID,
        )
    )

    assert first["work_stage_number"] == "2.6.6"
    assert first["canonical_stage_id"] == second["canonical_stage_id"]
    assert first["section_id"] == "load_bearing_walls"
    assert first["subtype_id"] == "block_walls"
    assert first["needs_review"] is False
    assert second["work_stage_number"] == "2.6.10"
    assert second["stage_occurrence_label"] == "2 этаж"
    assert second["section_id"] == "load_bearing_walls"
    assert second["subtype_id"] == "block_walls"


def test_stage_classifier_maps_selectable_and_grouped_options() -> None:
    classifier, stages = _classifier()

    slab = _raw(
        classifier.classify_row_to_stage(
            "Устройство утепленной шведской плиты",
            "work",
            stages,
            estimate_profile_id=ESTIMATE_TYPE_ID,
        )
    )
    roof = _raw(
        classifier.classify_row_to_stage(
            "Монтаж металлочерепицы",
            "work",
            stages,
            estimate_profile_id=ESTIMATE_TYPE_ID,
        )
    )

    assert slab["work_stage_number"] == "2.6.2"
    assert slab["stage_options_mode"] == "selectable_many"
    assert slab["stage_option_title"] == "УШП"
    assert slab["section_id"] == "foundation"
    assert slab["subtype_id"] == "slab_foundation"
    assert slab["needs_review"] is False
    assert roof["work_stage_number"] == "2.6.14"
    assert roof["stage_options_mode"] == "grouped_all"
    assert roof["stage_option_id"] == "roof_covering"
    assert roof["section_id"] == "roofing"
    assert roof["subtype_id"] == "pitched_roof_covering"
    assert roof["needs_review"] is False


def test_stage_classifier_does_not_autofill_roof_insulation_into_foundation_protection() -> None:
    classifier = StageClassifier(get_sequential_scoring_policy())
    stages = get_project_variant_stages(ESTIMATE_TYPE_ID, BRICK_PROJECT_VARIANT_ID)

    match = classifier.classify_row_to_stage(
        "Утепление кровли с подшивкой потолка и устройством пароизоляционного слоя",
        "work",
        stages,
        estimate_profile_id=ESTIMATE_TYPE_ID,
    )
    raw = match.as_raw_data(
        estimate_type_id=ESTIMATE_TYPE_ID,
        estimate_type_number="2",
        project_variant_id=BRICK_PROJECT_VARIANT_ID,
        project_variant_number="2.7",
        row_role="work",
    )

    assert raw["work_stage_number"] == "2.7.4"
    assert raw["needs_review"] is True
    assert raw["review_reason"] == "stage_weak_partial_text_match"
    assert raw["stage_match_score_json"]["needs_review"] is True


def test_stage_classifier_marks_generic_foundation_stage_as_review() -> None:
    classifier = StageClassifier(get_sequential_scoring_policy())
    stages = get_project_variant_stages(ESTIMATE_TYPE_ID, BRICK_PROJECT_VARIANT_ID)

    match = classifier.classify_row_to_stage(
        "Устройство фундамент",
        "work",
        stages,
        estimate_profile_id=ESTIMATE_TYPE_ID,
    )
    raw = match.as_raw_data(
        estimate_type_id=ESTIMATE_TYPE_ID,
        estimate_type_number="2",
        project_variant_id=BRICK_PROJECT_VARIANT_ID,
        project_variant_number="2.7",
        row_role="work",
    )

    assert raw["work_stage_number"] == "2.7.4"
    assert raw["needs_review"] is True
    assert raw["review_reason"] == "stage_weak_partial_text_match"
    assert raw["stage_match_score_json"]["needs_review"] is True


def test_stage_classifier_accepts_primary_work_type_despite_close_second_stage() -> None:
    classifier = StageClassifier(get_sequential_scoring_policy())
    stages = get_project_variant_stages(ESTIMATE_TYPE_ID, BRICK_PROJECT_VARIANT_ID)

    raw = _raw(
        classifier.classify_row_to_stage(
            "Монтаж перемычек",
            "work",
            stages,
            estimate_profile_id=ESTIMATE_TYPE_ID,
        )
    )

    assert raw["work_stage_number"] == "2.7.8"
    assert raw["needs_review"] is False
    assert raw["review_reason"] is None


def test_stage_classifier_material_inherits_previous_work_stage() -> None:
    classifier, stages = _classifier()
    work_match = classifier.classify_row_to_stage(
        "Кладка стен из газоблока",
        "work",
        stages,
        estimate_profile_id=ESTIMATE_TYPE_ID,
        row_order=0,
    )
    context = _raw(work_match)
    context["row_order"] = 0

    material = _raw(
        classifier.classify_row_to_stage(
            "Газоблок D500",
            "material",
            stages,
            context,
            estimate_profile_id=ESTIMATE_TYPE_ID,
            row_order=1,
        ),
        row_role="material",
    )

    assert material["work_stage_number"] == "2.6.6"
    assert material["row_role"] == "material"
    assert material["stage_match_type"] == "material_inherit"
    assert material["inherited_from_row_order"] == 0
    assert material["needs_review"] is False
    assert material["work_subtype_code"] is None


def test_row_role_legacy_mapping() -> None:
    assert normalize_row_role("delivery") == "logistics"
    assert normalize_row_role("equipment") == "mechanism"
    assert normalize_row_role("cleanup") == "logistics"
    assert normalize_row_role("unknown") == "unknown"
