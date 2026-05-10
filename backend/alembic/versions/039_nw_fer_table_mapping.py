"""
039_nw_fer_table_mapping.py
Маппинг ФЕР таблицы (fer.fer_tables) → NW.

Уровень детализации ниже, чем nw_fer_mapping (там был раздел).
Алгоритм заполнения — app.services.nw_classifier:
  1. OOS-маркеры в table_title → out_of_scope_subscope
  2. NW-precision keyword-правила → forced primary NW
  3. Остальное унаследовано от section (с понижением confidence)
  4. Тaбble без confident маппингов → отдельная запись needs_llm_review (nw_item_code IS NULL)

Confidence — только high/medium. Low в выход не попадает.
"""

from alembic import op
import sqlalchemy as sa


revision = "039_nw_fer_table_mapping"
down_revision = "038_nw_fer_mapping"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"

IN_SCOPE_COLLECTIONS = [
    1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 26, 27, 33, 34, 46, 47,
]


def upgrade():
    # ── DDL ──
    op.create_table(
        "nw_fer_table_mapping",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "fer_table_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.fer_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "nw_item_code",
            sa.String(length=10),
            sa.ForeignKey(f"{FER_SCHEMA}.nw_item.code", ondelete="CASCADE"),
            nullable=True,  # NULL для needs_llm_review записей
        ),
        sa.Column("mapping_type", sa.String(length=32), nullable=False),
        sa.Column("confidence",   sa.String(length=16), nullable=False),
        sa.Column("is_primary",   sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source",       sa.String(length=24), nullable=False),
        sa.Column("notes",        sa.Text(), nullable=True),
        # Уникальность пары (fer_table_id, nw_item_code).
        # PG считает NULL отличным от NULL → нескольких NULL допускает,
        # для needs_llm_review добавим partial unique index ниже.
        sa.UniqueConstraint(
            "fer_table_id", "nw_item_code",
            name="uq_nw_fer_table_mapping_table_nw",
        ),
        sa.CheckConstraint(
            "mapping_type IN ('direct','partial','composite_part','out_of_scope_subscope','needs_llm_review')",
            name="ck_nw_fer_table_mapping_type",
        ),
        sa.CheckConstraint(
            "confidence IN ('high','medium')",
            name="ck_nw_fer_table_mapping_confidence",
        ),
        sa.CheckConstraint(
            "(mapping_type = 'needs_llm_review' AND nw_item_code IS NULL) "
            "OR (mapping_type <> 'needs_llm_review' AND nw_item_code IS NOT NULL) "
            "OR mapping_type = 'out_of_scope_subscope'",
            name="ck_nw_fer_table_mapping_nw_consistency",
        ),
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_nw_fer_table_mapping_nw",
        "nw_fer_table_mapping", ["nw_item_code"],
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_nw_fer_table_mapping_table",
        "nw_fer_table_mapping", ["fer_table_id"],
        schema=FER_SCHEMA,
    )
    # Только одна needs_llm_review запись на таблицу
    op.execute(
        f"CREATE UNIQUE INDEX uq_nw_fer_table_mapping_table_unresolved "
        f"ON {FER_SCHEMA}.nw_fer_table_mapping (fer_table_id) "
        f"WHERE nw_item_code IS NULL"
    )

    # ── SEED через классификатор ──
    from app.services.nw_classifier import classify_table

    bind = op.get_bind()

    # 1. Все section-level маппинги в dict
    section_map: dict[tuple[int, int], list[dict]] = {}
    for r in bind.execute(sa.text(
        f"""
        SELECT fer_collection_num, fer_section_num,
               nw_item_code, mapping_type, confidence, is_primary, notes
        FROM {FER_SCHEMA}.nw_fer_mapping
        """
    )).mappings():
        key = (r["fer_collection_num"], r["fer_section_num"])
        section_map.setdefault(key, []).append(dict(r))

    # 2. Все in-scope таблицы с распарсенным sec_num
    in_scope_tuple = tuple(IN_SCOPE_COLLECTIONS)
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
    for t in bind.execute(tables_sql, {"in_scope": in_scope_tuple}).mappings():
        sm = section_map.get((t["coll_num"], t["sec_num"]), [])
        results = classify_table(t["coll_num"], t["table_title"] or "", sm)
        table_count += 1
        for r in results:
            rows_to_insert.append({
                "fer_table_id": t["table_id"],
                "nw_item_code": r.nw_item_code,
                "mapping_type": r.mapping_type,
                "confidence":   r.confidence,
                "is_primary":   r.is_primary,
                "source":       r.source,
                "notes":        r.notes,
            })

    # 3. bulk insert батчами по 1000 — на всякий случай
    BATCH = 1000
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
    for i in range(0, len(rows_to_insert), BATCH):
        op.bulk_insert(table_def, rows_to_insert[i:i + BATCH])

    # Лог в stdout (alembic его покажет)
    print(f"[039] классифицировано таблиц: {table_count}, вставлено строк: {len(rows_to_insert)}")


def downgrade():
    op.execute(
        f"DROP INDEX IF EXISTS {FER_SCHEMA}.uq_nw_fer_table_mapping_table_unresolved"
    )
    op.drop_index(
        "ix_nw_fer_table_mapping_table",
        table_name="nw_fer_table_mapping", schema=FER_SCHEMA,
    )
    op.drop_index(
        "ix_nw_fer_table_mapping_nw",
        table_name="nw_fer_table_mapping", schema=FER_SCHEMA,
    )
    op.drop_table("nw_fer_table_mapping", schema=FER_SCHEMA)
