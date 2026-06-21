from __future__ import annotations

from app.services.resource_classifier import (
    MODE_LABOR,
    MODE_MATERIALS,
    classify_estimate_row,
)
from app.services.work_taxonomy_service import (
    classify_work_cascade,
    get_project_variant_stages,
    get_variant_scope,
)


VARIANT_SCOPE = get_variant_scope("landscape_hardscape", "9.4")


def classify(item_text: str, title: str, description: str = ""):
    return classify_work_cascade(
        item_text,
        f"{title} {description}".strip(),
        section_title=title,
        section_description=description or None,
        row_role="work",
        variant_scope=VARIANT_SCOPE,
        allow_global_fallback=True,
    )


def test_geotextile_mirror_pair():
    foundation = classify(
        "Укладка геотекстиля на выровненные поверхности с подрезом",
        "Устройство фундамента забора",
        "Устройство ленточного фундамента забора",
    )
    paving = classify(
        "Укладка геотекстиля на выровненные поверхности с подрезом",
        "Пошаговые плиты",
        "Основание пошаговых плит в газоне",
    )
    assert foundation.subtype_code == "foundation/foundation_preparation_layers"
    assert foundation.preferred_stage_number == "9.4.3"
    assert paving.subtype_code == "landscape/base_geotextile_layers"
    assert paving.preferred_stage_number == "9.4.4"


def test_concrete_mirror_pair():
    foundation = classify(
        "Бетонные работы с армированием",
        "Устройство фундамента теплицы",
        "Устройство ленточного фундамента теплицы",
    )
    driveway = classify(
        "Бетонные работы с армированием",
        "Основание въезда. Тип 1",
        "Армированный бетон 15 см",
    )
    assert foundation.subtype_code == "foundation/foundation_rebar_formwork_concrete"
    assert driveway.subtype_code == "landscape/concrete_hardscape_base"


def test_compaction_mirror_pair():
    foundation = classify(
        "Трамбование. Механический способ",
        "Устройство фундамента забора",
        "Устройство ленточного фундамента забора",
    )
    paving = classify(
        "Вибротрамбование песка. Механический способ",
        "Пошаговые плиты",
        "Основание пошаговых плит в газоне",
    )
    assert foundation.operation_code == "compaction"
    assert foundation.subtype_code == "foundation/foundation_preparation_layers"
    assert paving.operation_code == "compaction"
    assert paving.subtype_code == "landscape/gravel_sand_base"


def test_mixed_object_art_wall():
    title = "Устройство стены для АРТ-объекта"
    description = "Устройство ленточного фундамента для установки стены из блоков"
    concrete = classify("Бетонные работы с армированием", title, description)
    masonry = classify(
        "Выполнение кладки из керамических блоков",
        title,
        description,
    )
    codes = {
        item["object_scope_code"]
        for item in masonry.section_object_candidates
    }
    assert {"foundation", "decorative_wall"} <= codes
    assert concrete.subtype_code == "foundation/foundation_rebar_formwork_concrete"
    assert concrete.selected_object_scope_code == "foundation"
    assert masonry.subtype_code == "landscape/decorative_block_walls"
    assert masonry.selected_object_scope_code == "decorative_wall"
    assert masonry.preferred_stage_number == "9.4.6"


def test_resource_roles():
    unload = classify_estimate_row(
        name="Разгрузка брусчатки вручную",
        unit="кв.м",
        current_mode=MODE_LABOR,
    )
    delivery = classify_estimate_row(
        name="Доставка спецтехники",
        spec="Низкорамный трал, аренда",
        unit="рейс",
        current_mode=MODE_MATERIALS,
    )
    machine = classify_estimate_row(
        name="Спецтехника для планировки",
        spec="Мини погрузчик с оператором",
        unit="смена",
        current_mode=MODE_MATERIALS,
    )
    supervision = classify_estimate_row(
        name="Надзор за спецтехникой",
        unit="смена",
        current_mode=MODE_LABOR,
    )
    disposal = classify_estimate_row(
        name="Утилизация грунта самосвалами",
        spec="С погрузкой",
        unit="куб.м",
        current_mode=MODE_LABOR,
    )
    assert unload.row_role_hint == "logistics"
    assert delivery.row_role_hint == "logistics"
    assert machine.item_type == "mechanism"
    assert supervision.item_type == "overhead"
    assert disposal.item_type == "work"
    assert disposal.row_role_hint == "work"


def test_stage_9411_exists():
    stages = get_project_variant_stages("landscape_hardscape", "9.4")
    stage = next(item for item in stages if item["number"] == "9.4.11")
    assert stage["stage_options_mode"] == "grouped_all"
    assert stage["primary_work_type"]["section_id"] == "landscape"
    assert stage["primary_work_type"]["subtype_id"] == "landscape_grading"
