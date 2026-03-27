"""
009_enir_machine_coefficients.py
Добавляет машиночитаемые условия коэффициентов и таблицу технических коэффициентов ENIR.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enir_source_notes", sa.Column("conditions", JSONB(), nullable=True))
    op.add_column("enir_source_notes", sa.Column("formula", sa.Text(), nullable=True))

    op.add_column("enir_notes", sa.Column("conditions", JSONB(), nullable=True))
    op.add_column("enir_notes", sa.Column("formula", sa.Text(), nullable=True))

    op.add_column("enir_norm_rows", sa.Column("params", JSONB(), nullable=True))
    op.add_column("enir_norm_values", sa.Column("value_numeric", sa.Numeric(12, 4), nullable=True))

    op.create_table(
        "enir_technical_coefficients",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_sections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "chapter_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_chapters.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "paragraph_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("multiplier", sa.Numeric(8, 4), nullable=True),
        sa.Column("conditions", JSONB(), nullable=True),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "num_nonnulls(section_id, chapter_id, paragraph_id) <= 1",
            name="ck_enir_tc_one_scope",
        ),
    )
    op.create_index(
        "ix_enir_tc_collection_id",
        "enir_technical_coefficients",
        ["collection_id"],
    )
    op.create_index(
        "ix_enir_tc_section_id",
        "enir_technical_coefficients",
        ["section_id"],
        unique=False,
        postgresql_where=sa.text("section_id IS NOT NULL"),
    )
    op.create_index(
        "ix_enir_tc_chapter_id",
        "enir_technical_coefficients",
        ["chapter_id"],
        unique=False,
        postgresql_where=sa.text("chapter_id IS NOT NULL"),
    )
    op.create_index(
        "ix_enir_tc_paragraph_id",
        "enir_technical_coefficients",
        ["paragraph_id"],
        unique=False,
        postgresql_where=sa.text("paragraph_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("ix_enir_tc_paragraph_id", table_name="enir_technical_coefficients")
    op.drop_index("ix_enir_tc_chapter_id", table_name="enir_technical_coefficients")
    op.drop_index("ix_enir_tc_section_id", table_name="enir_technical_coefficients")
    op.drop_index("ix_enir_tc_collection_id", table_name="enir_technical_coefficients")
    op.drop_table("enir_technical_coefficients")

    op.drop_column("enir_norm_values", "value_numeric")
    op.drop_column("enir_norm_rows", "params")

    op.drop_column("enir_notes", "formula")
    op.drop_column("enir_notes", "conditions")

    op.drop_column("enir_source_notes", "formula")
    op.drop_column("enir_source_notes", "conditions")
