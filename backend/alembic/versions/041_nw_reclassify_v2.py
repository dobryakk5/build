"""
041_nw_reclassify_v2.py
Второй перепрогон классификатора после расширения правил:
  • Новые OOS-маркеры:
    - резервуары для нефти/нефтепродуктов (Сб.9.2)
    - промышленные эстакады (под/для/межцеховые)
    - meta-расценки «расценки для корректировки таблиц»
    - отделка/устройство печей (устаревший тип отопления)
  • Новые NW-precision правила:
    - шпатлёвка → NW-030 (черновая отделка)
    - отбойники / защита углов → NW-031
    - перегородки в зданиях → NW-026 (для разделов где inheritance не сработал)
    - алмазное бурение / сверление в ж/б при реконструкции → NW-035 (Сб.46)
    - ж/б ёмкости водопровода/канализации → NW-061 (Сб.6.13)
    - временные здания и их инженерия → NW-001 (Сб.21)

Прогноз: needs_llm 357 → 329, covered 1669 → 1684, oos 395 → 408.
"""

from alembic import op
import sqlalchemy as sa


revision = "041_nw_reclassify_v2"
down_revision = "040_nw_reclassify"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"

IN_SCOPE_COLLECTIONS = [
    1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 26, 27, 33, 34, 46, 47,
]


def _reclassify():
    from app.services.nw_classifier import classify_table

    bind = op.get_bind()

    section_map: dict[tuple[int, int], list[dict]] = {}
    for r in bind.execute(sa.text(
        f"""
        SELECT fer_collection_num, fer_section_num,
               nw_item_code, mapping_type, confidence, is_primary, notes
        FROM {FER_SCHEMA}.nw_fer_mapping
        """
    )).mappings():
        section_map.setdefault(
            (r["fer_collection_num"], r["fer_section_num"]), []
        ).append(dict(r))

    tables_sql = sa.text(
        rf"""
        SELECT
            t.id  AS table_id,
            c.num::int AS coll_num,
            CAST(substring(s.title from '^Раздел\s+(\d+)') AS int) AS sec_num,
            t.table_title
        FROM {FER_SCHEMA}.fer_tables t
        JOIN {FER_SCHEMA}.collections c ON c.id = t.collection_id
        JOIN {FER_SCHEMA}.sections s    ON s.id = t.section_id
        WHERE c.num ~ '^[0-9]+$'
          AND c.num::int IN :in_scope
          AND substring(s.title from '^Раздел\s+(\d+)') ~ '^[0-9]+$'
          AND NOT COALESCE(t.ignored, FALSE)
        """
    ).bindparams(sa.bindparam("in_scope", expanding=True))

    rows_to_insert: list[dict] = []
    table_count = 0
    for t in bind.execute(tables_sql, {"in_scope": tuple(IN_SCOPE_COLLECTIONS)}).mappings():
        sm = section_map.get((t["coll_num"], t["sec_num"]), [])
        for r in classify_table(t["coll_num"], t["table_title"] or "", sm):
            rows_to_insert.append({
                "fer_table_id": t["table_id"],
                "nw_item_code": r.nw_item_code,
                "mapping_type": r.mapping_type,
                "confidence":   r.confidence,
                "is_primary":   r.is_primary,
                "source":       r.source,
                "notes":        r.notes,
            })
        table_count += 1

    table_def = sa.table(
        "nw_fer_table_mapping",
        sa.column("fer_table_id", sa.BigInteger),
        sa.column("nw_item_code", sa.String),
        sa.column("mapping_type", sa.String),
        sa.column("confidence",   sa.String),
        sa.column("is_primary",   sa.Boolean),
        sa.column("source",       sa.String),
        sa.column("notes",        sa.Text),
        schema=FER_SCHEMA,
    )
    BATCH = 1000
    for i in range(0, len(rows_to_insert), BATCH):
        op.bulk_insert(table_def, rows_to_insert[i:i + BATCH])

    print(f"[041] reclassified {table_count} tables, inserted {len(rows_to_insert)} rows")


def upgrade():
    op.execute(f"DELETE FROM {FER_SCHEMA}.nw_fer_table_mapping")
    _reclassify()


def downgrade():
    op.execute(f"DELETE FROM {FER_SCHEMA}.nw_fer_table_mapping")
    _reclassify()
