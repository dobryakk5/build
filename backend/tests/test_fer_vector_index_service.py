from app.services.fer_vector_index_service import (
    PilotFerRow,
    build_row_record,
    build_row_search_text,
    checksum_text,
    format_vector,
)


def test_build_row_search_text_contains_hierarchy():
    row = PilotFerRow(
        collection_id=1,
        collection_num="01",
        collection_name="Земляные работы",
        section_id=10,
        section_title="Раздел 1",
        subsection_id=20,
        subsection_title="Подраздел 1.1",
        table_id=30,
        table_title="Разработка грунта",
        common_work_name="Разработка грунта экскаваторами",
        row_id=40,
        row_slug="/fer/example",
        clarification="15 м3, группа грунтов 1 — 1000 м3",
    )

    text = build_row_search_text(row)

    assert "Сборник 01 Земляные работы" in text
    assert "Раздел: Раздел 1" in text
    assert "Подраздел: Подраздел 1.1" in text
    assert "Таблица: Разработка грунта экскаваторами" in text
    assert "Уточнение: 15 м3, группа грунтов 1 — 1000 м3" in text


def test_checksum_text_is_stable():
    assert checksum_text("abc") == checksum_text("abc")
    assert checksum_text("abc") != checksum_text("abcd")


def test_format_vector_pgvector_literal():
    assert format_vector([0.5, 1.25, -2.0]).startswith("[")
    assert format_vector([0.5, 1.25, -2.0]).endswith("]")
    assert "," in format_vector([0.5, 1.25, -2.0])


def test_build_row_record_populates_fts_document():
    row = PilotFerRow(
        collection_id=1,
        collection_num="08",
        collection_name="Конструкции из кирпича и блоков",
        section_id=2,
        section_title="Каменные конструкции",
        subsection_id=3,
        subsection_title="Стены",
        table_id=4,
        table_title="Кладка стен",
        common_work_name="Кладка кирпичных стен",
        row_id=5,
        row_slug=None,
        clarification="простых при высоте этажа до 4 м",
    )

    record = build_row_record(row, [0.1, 0.2])

    assert "Кладка кирпичных стен" in record.fts_document
    assert "простых при высоте этажа до 4 м" in record.fts_document
