"""
006_enir_norm_tables_jsonb.py
Переводит хранение норм ЕНИР в enir_norm_tables с JSONB-колонками columns/rows.
Также пересоздаёт enir_estimate_mappings без FK на плоскую таблицу enir_norms.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import TIMESTAMP

TIMESTAMPTZ = TIMESTAMP(timezone=True)

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("enir_estimate_mappings")
    op.drop_table("enir_group_mappings")
    op.drop_table("enir_norms")

    op.create_table(
        "enir_norm_tables",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("table_id", sa.String(length=120), nullable=False),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("columns", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rows", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.UniqueConstraint("table_id", name="uq_enir_norm_table_id"),
    )
    op.create_index("ix_enir_norm_tables_paragraph_id", "enir_norm_tables", ["paragraph_id"])

    op.create_table(
        "enir_group_mappings",
        sa.Column("id",            sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id",    UUID,
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id",       UUID,
                  sa.ForeignKey("gantt_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_id", sa.BigInteger(),
                  sa.ForeignKey("enir_collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status",       sa.String(20), nullable=False, server_default="ai_suggested"),
        sa.Column("confidence",   sa.Numeric(4, 3), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("alternatives", sa.Text(), nullable=True),
        sa.Column("created_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.Column("updated_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("task_id", name="uq_enir_group_mapping_task"),
    )
    op.create_index("ix_enir_gmap_project_id", "enir_group_mappings", ["project_id"])

    op.create_table(
        "enir_estimate_mappings",
        sa.Column("id",               sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id",       UUID,
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_mapping_id", sa.BigInteger(),
                  sa.ForeignKey("enir_group_mappings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("estimate_id",      UUID,
                  sa.ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paragraph_id",     sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("norm_row_id",      sa.String(length=120), nullable=True),
        sa.Column("norm_row_hint",    sa.Text(), nullable=True),
        sa.Column("status",       sa.String(20), nullable=False, server_default="ai_suggested"),
        sa.Column("confidence",   sa.Numeric(4, 3), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("alternatives", sa.Text(), nullable=True),
        sa.Column("created_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.Column("updated_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("estimate_id", name="uq_enir_estimate_mapping_estimate"),
    )
    op.create_index("ix_enir_emap_project_id", "enir_estimate_mappings", ["project_id"])
    op.create_index("ix_enir_emap_group_mapping", "enir_estimate_mappings", ["group_mapping_id"])


def downgrade():
    op.drop_table("enir_estimate_mappings")
    op.drop_table("enir_group_mappings")
    op.drop_table("enir_norm_tables")

    op.create_table(
        "enir_norms",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("paragraph_id", sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_num", sa.SmallInteger(), nullable=False),
        sa.Column("work_type", sa.Text(), nullable=True),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("thickness_mm", sa.Integer(), nullable=True),
        sa.Column("column_label", sa.String(length=10), nullable=True),
        sa.Column("norm_time", sa.Numeric(10, 4), nullable=True),
        sa.Column("price_rub", sa.Numeric(12, 4), nullable=True),
    )
    op.create_index("ix_enir_norms_paragraph_id", "enir_norms", ["paragraph_id"])

    op.create_table(
        "enir_group_mappings",
        sa.Column("id",            sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id",    UUID,
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id",       UUID,
                  sa.ForeignKey("gantt_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_id", sa.BigInteger(),
                  sa.ForeignKey("enir_collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status",       sa.String(20), nullable=False, server_default="ai_suggested"),
        sa.Column("confidence",   sa.Numeric(4, 3), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("alternatives", sa.Text(), nullable=True),
        sa.Column("created_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.Column("updated_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("task_id", name="uq_enir_group_mapping_task"),
    )
    op.create_index("ix_enir_gmap_project_id", "enir_group_mappings", ["project_id"])

    op.create_table(
        "enir_estimate_mappings",
        sa.Column("id",               sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id",       UUID,
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_mapping_id", sa.BigInteger(),
                  sa.ForeignKey("enir_group_mappings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("estimate_id",      UUID,
                  sa.ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paragraph_id",     sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("norm_row_id",      sa.BigInteger(),
                  sa.ForeignKey("enir_norms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("norm_row_hint",    sa.Text(), nullable=True),
        sa.Column("status",       sa.String(20), nullable=False, server_default="ai_suggested"),
        sa.Column("confidence",   sa.Numeric(4, 3), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("alternatives", sa.Text(), nullable=True),
        sa.Column("created_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.Column("updated_at",   TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("estimate_id", name="uq_enir_estimate_mapping_estimate"),
    )
    op.create_index("ix_enir_emap_project_id", "enir_estimate_mappings", ["project_id"])
    op.create_index("ix_enir_emap_group_mapping", "enir_estimate_mappings", ["group_mapping_id"])
