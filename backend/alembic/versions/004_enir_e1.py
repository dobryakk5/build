"""
004_enir_e1.py
Расширение схемы ENIR для полной загрузки нормализованного формата E1.

Добавляет:
  - metadata/source-поля у сборников и параграфов
  - таблицы raw/source-данных E1
  - табличную модель норм table/column/row/value
  - nullable row_num у enir_norms для совместимости с данными без номера строки
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import NUMERIC

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enir_collections", sa.Column("source_file", sa.Text(), nullable=True))
    op.add_column("enir_collections", sa.Column("source_format", sa.String(length=50), nullable=True))

    op.add_column("enir_paragraphs", sa.Column("source_paragraph_id", sa.String(length=60), nullable=True))
    op.alter_column("enir_norms", "row_num", existing_type=sa.SmallInteger(), nullable=True)

    op.create_table(
        "enir_paragraph_technical_characteristics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_text", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_enir_ptc_paragraph_id",
        "enir_paragraph_technical_characteristics",
        ["paragraph_id"],
    )

    op.create_table(
        "enir_paragraph_application_notes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_enir_pan_paragraph_id",
        "enir_paragraph_application_notes",
        ["paragraph_id"],
    )

    op.create_table(
        "enir_source_work_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_text", sa.Text(), nullable=False),
    )
    op.create_index("ix_enir_swi_paragraph_id", "enir_source_work_items", ["paragraph_id"])

    op.create_table(
        "enir_source_crew_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profession", sa.String(length=200)),
        sa.Column("grade", NUMERIC(4, 1)),
        sa.Column("count", sa.SmallInteger()),
        sa.Column("raw_text", sa.Text()),
    )
    op.create_index("ix_enir_sci_paragraph_id", "enir_source_crew_items", ["paragraph_id"])

    op.create_table(
        "enir_source_notes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("code", sa.String(length=20)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("coefficient", NUMERIC(6, 4)),
    )
    op.create_index("ix_enir_sn_paragraph_id", "enir_source_notes", ["paragraph_id"])

    op.create_table(
        "enir_norm_tables",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_table_id", sa.String(length=120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.Text()),
        sa.Column("row_count", sa.Integer()),
        sa.UniqueConstraint("source_table_id", name="uq_enir_norm_table_source_id"),
    )
    op.create_index("ix_enir_nt_paragraph_id", "enir_norm_tables", ["paragraph_id"])

    op.create_table(
        "enir_norm_columns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("norm_table_id", sa.BigInteger(),
                  sa.ForeignKey("enir_norm_tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_column_key", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("header", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=20)),
        sa.UniqueConstraint("norm_table_id", "source_column_key", name="uq_enir_norm_column_key"),
    )
    op.create_index("ix_enir_nc_table_id", "enir_norm_columns", ["norm_table_id"])

    op.create_table(
        "enir_norm_rows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("norm_table_id", sa.BigInteger(),
                  sa.ForeignKey("enir_norm_tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_row_id", sa.String(length=140), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_row_num", sa.SmallInteger()),
        sa.UniqueConstraint("source_row_id", name="uq_enir_norm_row_source_id"),
    )
    op.create_index("ix_enir_nr_table_id", "enir_norm_rows", ["norm_table_id"])

    op.create_table(
        "enir_norm_values",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("norm_row_id", sa.BigInteger(),
                  sa.ForeignKey("enir_norm_rows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("norm_column_id", sa.BigInteger(),
                  sa.ForeignKey("enir_norm_columns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value_type", sa.String(length=30), nullable=False),
        sa.Column("value_text", sa.Text()),
    )
    op.create_index("ix_enir_nv_row_id", "enir_norm_values", ["norm_row_id"])
    op.create_index("ix_enir_nv_column_id", "enir_norm_values", ["norm_column_id"])


def downgrade():
    op.drop_table("enir_norm_values")
    op.drop_table("enir_norm_rows")
    op.drop_table("enir_norm_columns")
    op.drop_table("enir_norm_tables")
    op.drop_table("enir_source_notes")
    op.drop_table("enir_source_crew_items")
    op.drop_table("enir_source_work_items")
    op.drop_table("enir_paragraph_application_notes")
    op.drop_table("enir_paragraph_technical_characteristics")
    op.alter_column("enir_norms", "row_num", existing_type=sa.SmallInteger(), nullable=False)
    op.drop_column("enir_paragraphs", "source_paragraph_id")
    op.drop_column("enir_collections", "source_format")
    op.drop_column("enir_collections", "source_file")
