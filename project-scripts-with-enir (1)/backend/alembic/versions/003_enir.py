"""
003_enir.py
Таблицы справочника ЕНИР.

Иерархия:
  enir_collections
    └─ enir_paragraphs
         ├─ enir_work_compositions → enir_work_operations
         ├─ enir_crew_members
         ├─ enir_norms
         └─ enir_notes
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy import TIMESTAMP

TIMESTAMPTZ = TIMESTAMP(timezone=True)

revision      = "003"
down_revision = "002"
branch_labels = None
depends_on    = None


def upgrade():

    # ── 1. Сборники ────────────────────────────────────────────────────────
    op.create_table(
        "enir_collections",
        sa.Column("id",          sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code",        sa.String(20),   nullable=False),
        sa.Column("title",       sa.Text(),        nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("sort_order",  sa.Integer(),     nullable=False, server_default="0"),
        sa.Column("created_at",  TIMESTAMPTZ,      server_default=sa.text("NOW()")),
        sa.UniqueConstraint("code", name="uq_enir_collection_code"),
    )

    # ── 2. Параграфы ───────────────────────────────────────────────────────
    op.create_table(
        "enir_paragraphs",
        sa.Column("id",            sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("collection_id", sa.BigInteger(),
                  sa.ForeignKey("enir_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code",          sa.String(30),   nullable=False),
        sa.Column("title",         sa.Text(),        nullable=False),
        sa.Column("unit",          sa.String(100)),
        sa.Column("sort_order",    sa.Integer(),     nullable=False, server_default="0"),
        sa.UniqueConstraint("collection_id", "code", name="uq_enir_paragraph_code"),
    )
    op.create_index("ix_enir_paragraphs_collection_id", "enir_paragraphs", ["collection_id"])

    # ── 3. Состав работ ────────────────────────────────────────────────────
    op.create_table(
        "enir_work_compositions",
        sa.Column("id",           sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("condition",    sa.Text()),
        sa.Column("sort_order",   sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_enir_wcomp_paragraph_id", "enir_work_compositions", ["paragraph_id"])

    op.create_table(
        "enir_work_operations",
        sa.Column("id",             sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("composition_id", sa.BigInteger(),
                  sa.ForeignKey("enir_work_compositions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text",           sa.Text(), nullable=False),
        sa.Column("sort_order",     sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_enir_wop_composition_id", "enir_work_operations", ["composition_id"])

    # ── 4. Состав звена ────────────────────────────────────────────────────
    op.create_table(
        "enir_crew_members",
        sa.Column("id",           sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profession",   sa.String(200), nullable=False),
        sa.Column("grade",        NUMERIC(4, 1)),            # разряд (м.б. дробный)
        sa.Column("count",        sa.SmallInteger(), nullable=False, server_default="1"),
    )
    op.create_index("ix_enir_crew_paragraph_id", "enir_crew_members", ["paragraph_id"])

    # ── 5. Нормы ───────────────────────────────────────────────────────────
    op.create_table(
        "enir_norms",
        sa.Column("id",           sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_num",      sa.SmallInteger(), nullable=False),
        sa.Column("work_type",    sa.Text()),
        sa.Column("condition",    sa.Text()),
        sa.Column("thickness_mm", sa.Integer()),
        sa.Column("column_label", sa.String(10)),
        sa.Column("norm_time",    NUMERIC(10, 4)),
        sa.Column("price_rub",    NUMERIC(12, 4)),
    )
    op.create_index("ix_enir_norms_paragraph_id", "enir_norms", ["paragraph_id"])

    # ── 6. Примечания ──────────────────────────────────────────────────────
    op.create_table(
        "enir_notes",
        sa.Column("id",           sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("num",          sa.SmallInteger(), nullable=False),
        sa.Column("text",         sa.Text(), nullable=False),
        sa.Column("coefficient",  NUMERIC(6, 4)),
        sa.Column("pr_code",      sa.String(20)),
    )
    op.create_index("ix_enir_notes_paragraph_id", "enir_notes", ["paragraph_id"])


def downgrade():
    op.drop_table("enir_notes")
    op.drop_table("enir_norms")
    op.drop_table("enir_crew_members")
    op.drop_table("enir_work_operations")
    op.drop_table("enir_work_compositions")
    op.drop_table("enir_paragraphs")
    op.drop_table("enir_collections")
