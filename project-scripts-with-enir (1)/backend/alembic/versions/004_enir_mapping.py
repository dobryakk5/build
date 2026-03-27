"""
004_enir_mapping.py
Таблицы маппинга сметы → ЕНИР.

  enir_group_mappings     — группа Ганта → сборник ЕНИР  (этап 1)
  enir_estimate_mappings  — строка сметы → параграф ЕНИР (этап 2)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import NUMERIC, UUID
from sqlalchemy import TIMESTAMP

TIMESTAMPTZ = TIMESTAMP(timezone=True)

revision      = "004"
down_revision = "003"
branch_labels = None
depends_on    = None


def upgrade():

    # ── 1. Группа → сборник ────────────────────────────────────────────────
    op.create_table(
        "enir_group_mappings",
        sa.Column("id",            sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id",    UUID,
                  sa.ForeignKey("projects.id",          ondelete="CASCADE"), nullable=False),
        sa.Column("task_id",       UUID,
                  sa.ForeignKey("gantt_tasks.id",        ondelete="CASCADE"), nullable=False),
        sa.Column("collection_id", sa.BigInteger(),
                  sa.ForeignKey("enir_collections.id",  ondelete="SET NULL"), nullable=True),

        # status: ai_suggested | confirmed | rejected | manual
        sa.Column("status",       sa.String(20),  nullable=False, server_default="ai_suggested"),
        sa.Column("confidence",   NUMERIC(4, 3),  nullable=True),
        sa.Column("ai_reasoning", sa.Text(),       nullable=True),
        sa.Column("alternatives", sa.Text(),       nullable=True),  # JSON

        sa.Column("created_at",   TIMESTAMPTZ,    server_default=sa.text("NOW()")),
        sa.Column("updated_at",   TIMESTAMPTZ,    server_default=sa.text("NOW()")),

        sa.UniqueConstraint("task_id", name="uq_enir_group_mapping_task"),
    )
    op.create_index("ix_enir_gmap_project_id", "enir_group_mappings", ["project_id"])

    # ── 2. Строка сметы → параграф ────────────────────────────────────────
    op.create_table(
        "enir_estimate_mappings",
        sa.Column("id",               sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id",       UUID,
                  sa.ForeignKey("projects.id",         ondelete="CASCADE"), nullable=False),
        sa.Column("group_mapping_id", sa.BigInteger(),
                  sa.ForeignKey("enir_group_mappings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("estimate_id",      UUID,
                  sa.ForeignKey("estimates.id",         ondelete="CASCADE"), nullable=False),
        sa.Column("paragraph_id",     sa.BigInteger(),
                  sa.ForeignKey("enir_paragraphs.id",   ondelete="SET NULL"), nullable=True),

        # Вариант В: текст + слабая ссылка на строку нормы
        sa.Column("norm_row_id",      sa.BigInteger(),
                  sa.ForeignKey("enir_norms.id",        ondelete="SET NULL"), nullable=True),
        sa.Column("norm_row_hint",    sa.Text(),         nullable=True),

        sa.Column("status",       sa.String(20),  nullable=False, server_default="ai_suggested"),
        sa.Column("confidence",   NUMERIC(4, 3),  nullable=True),
        sa.Column("ai_reasoning", sa.Text(),       nullable=True),
        sa.Column("alternatives", sa.Text(),       nullable=True),  # JSON

        sa.Column("created_at",   TIMESTAMPTZ,    server_default=sa.text("NOW()")),
        sa.Column("updated_at",   TIMESTAMPTZ,    server_default=sa.text("NOW()")),

        sa.UniqueConstraint("estimate_id", name="uq_enir_estimate_mapping_estimate"),
    )
    op.create_index("ix_enir_emap_project_id",     "enir_estimate_mappings", ["project_id"])
    op.create_index("ix_enir_emap_group_mapping",  "enir_estimate_mappings", ["group_mapping_id"])


def downgrade():
    op.drop_table("enir_estimate_mappings")
    op.drop_table("enir_group_mappings")
