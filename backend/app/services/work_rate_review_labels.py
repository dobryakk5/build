"""Human-readable labels for classification and work-rate review reasons."""
from __future__ import annotations

CLASSIFICATION_REVIEW_LABELS = {
    "internal_wall_insulation_exception": (
        "Обнаружено внутреннее утепление. Выберите тип работы вручную."
    ),
    "brick_pillar_object_not_resolved": (
        "Не определено, относится кирпичный столб к зданию или ограждению."
    ),
}

RATE_REVIEW_LABELS = {
    "masonry_location_not_resolved": (
        "Не определено, относится кладка к наружной или внутренней стене."
    ),
    "masonry_location_conflict": (
        "В одной строке одновременно указаны наружные и внутренние стены. "
        "Разделите объёмы или выберите расценку вручную."
    ),
    "brick_pillar_rate_not_available": (
        "Для кирпичных столбов отдельная расценка не задана."
    ),
    "vent_shaft_masonry_rate_not_available": (
        "Для кирпичной кладки вентканалов отдельная расценка не задана."
    ),
    "special_masonry_operation_mismatch": (
        "Обнаружен специальный вид кладки, но строка классифицирована "
        "как обычная кладка стен."
    ),
    "facade_cladding_rate_not_available": (
        "Для фасадной облицовки не найдена совместимая утверждённая расценка."
    ),
    "unit_incompatible": (
        "Единица строки несовместима с единицей расценки."
    ),
    "multiple_equivalent_rate_candidates": (
        "Найдено несколько равноценных расценок."
    ),
    "operation_resolution_failed": (
        "Не удалось однозначно определить операцию для подбора расценки."
    ),
}


def classification_review_label(reason: str | None) -> str | None:
    return CLASSIFICATION_REVIEW_LABELS.get(reason) if reason else None


def rate_review_label(reason: str | None) -> str | None:
    return RATE_REVIEW_LABELS.get(reason) if reason else None
