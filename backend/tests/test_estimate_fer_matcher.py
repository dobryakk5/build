from types import SimpleNamespace

from app.services.estimate_fer_matcher import _build_estimate_search_text, _format_vector


def test_build_estimate_search_text_includes_section_work_and_unit():
    estimate = SimpleNamespace(
        section="Фундамент",
        work_name="Устройство монолитной плиты",
        unit="м3",
    )

    text = _build_estimate_search_text(estimate)

    assert "Раздел: Фундамент" in text
    assert "Работа: Устройство монолитной плиты" in text
    assert "Единица: м3" in text


def test_build_estimate_search_text_omits_empty_fields():
    estimate = SimpleNamespace(
        section="",
        work_name="Монтаж каркаса",
        unit=None,
    )

    text = _build_estimate_search_text(estimate)

    assert text == "Работа: Монтаж каркаса"


def test_format_vector_returns_pgvector_literal():
    value = _format_vector([0.5, 1.25, -2.0])

    assert value.startswith("[")
    assert value.endswith("]")
    assert "," in value
