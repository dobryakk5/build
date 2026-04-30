from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "036_ktp_groups_and_cards"
down_revision = "035_foreman_task_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ktp_groups",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "estimate_batch_id",
            UUID(as_uuid=False),
            sa.ForeignKey("estimate_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group_key", sa.String(512), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("estimate_ids", JSONB(), nullable=False, server_default="[]"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_price", sa.Numeric(16, 2), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="new"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id",
            "estimate_batch_id",
            "group_key",
            name="uq_ktp_groups_project_batch_key",
        ),
    )
    op.create_index(
        "ix_ktp_groups_project_batch",
        "ktp_groups",
        ["project_id", "estimate_batch_id"],
    )
    op.create_index("ix_ktp_groups_status", "ktp_groups", ["status"])

    op.create_table(
        "ktp_cards",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "estimate_batch_id",
            UUID(as_uuid=False),
            sa.ForeignKey("estimate_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ktp_group_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ktp_groups.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("steps_json", JSONB(), nullable=True),
        sa.Column("recommendations_json", JSONB(), nullable=True),
        sa.Column("questions_json", JSONB(), nullable=True),
        sa.Column("answers_json", JSONB(), nullable=True),
        sa.Column("llm_model", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ktp_cards_project_batch",
        "ktp_cards",
        ["project_id", "estimate_batch_id"],
    )
    op.create_index("ix_ktp_cards_group", "ktp_cards", ["ktp_group_id"])


def downgrade():
    op.drop_index("ix_ktp_cards_group", table_name="ktp_cards")
    op.drop_index("ix_ktp_cards_project_batch", table_name="ktp_cards")
    op.drop_table("ktp_cards")
    op.drop_index("ix_ktp_groups_status", table_name="ktp_groups")
    op.drop_index("ix_ktp_groups_project_batch", table_name="ktp_groups")
    op.drop_table("ktp_groups")
