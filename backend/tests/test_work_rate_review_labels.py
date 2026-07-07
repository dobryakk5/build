from app.services.work_rate_review_labels import rate_review_label


def test_membrane_context_review_reason_has_human_readable_label():
    assert rate_review_label("membrane_context_not_resolved") == (
        "Не удалось определить тип мембраны и место её монтажа."
    )


def test_rate_variant_review_reason_has_human_readable_label():
    assert rate_review_label("rate_variant_required") == (
        "Не хватает обязательных параметров работы для выбора подходящей нормы."
    )
