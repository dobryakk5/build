from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "046_ktp_estimate_flow"
down_revision = "045_ktp_group_wt_match_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ktp_estimate_sessions",
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
            "status", sa.String(32), nullable=False, server_default="stage1_pending"
        ),
        sa.Column(
            "stage1_job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "gpr_job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage1_raw_json", JSONB(), nullable=True),
        sa.Column("llm_model", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
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
        sa.UniqueConstraint(
            "project_id",
            "estimate_batch_id",
            name="uq_ktp_estimate_sessions_project_batch",
        ),
    )
    op.create_index(
        "ix_ktp_estimate_sessions_batch",
        "ktp_estimate_sessions",
        ["estimate_batch_id"],
    )

    op.create_table(
        "ktp_wbs_groups",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ktp_estimate_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "sort_order", sa.Numeric(20, 10), nullable=False, server_default="1000"
        ),
        sa.Column("wt_code", sa.String(10), nullable=True),
        sa.Column("wt_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("card_title", sa.Text(), nullable=True),
        sa.Column("card_goal", sa.Text(), nullable=True),
        sa.Column("card_steps_json", JSONB(), nullable=True),
        sa.Column("card_recommendations_json", JSONB(), nullable=True),
        sa.Column("card_questions_json", JSONB(), nullable=True),
        sa.Column("card_answers_json", JSONB(), nullable=True),
        sa.Column("card_error_message", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column(
            "gantt_task_id",
            UUID(as_uuid=False),
            sa.ForeignKey("gantt_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        "ix_ktp_wbs_groups_session", "ktp_wbs_groups", ["session_id"]
    )

    op.create_table(
        "ktp_wbs_items",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "group_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ktp_wbs_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ktp_estimate_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "sort_order", sa.Numeric(20, 10), nullable=False, server_default="1000"
        ),
        sa.Column(
            "origin", sa.String(16), nullable=False, server_default="from_estimate"
        ),
        sa.Column(
            "estimate_id",
            UUID(as_uuid=False),
            sa.ForeignKey("estimates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("quantity_source", sa.String(16), nullable=True),
        sa.Column(
            "review_status", sa.String(16), nullable=False, server_default="accepted"
        ),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("norm_source", sa.String(8), nullable=True),
        sa.Column("norm_ref", sa.String(64), nullable=True),
        sa.Column("norm_kind", sa.String(12), nullable=True),
        sa.Column("norm_value", sa.Numeric(12, 4), nullable=True),
        sa.Column("norm_unit", sa.String(32), nullable=True),
        sa.Column("brigade_size", sa.SmallInteger(), nullable=True),
        sa.Column("labor_hours", sa.Numeric(12, 2), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column(
            "gantt_task_id",
            UUID(as_uuid=False),
            sa.ForeignKey("gantt_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_ktp_wbs_items_group", "ktp_wbs_items", ["group_id"])
    op.create_index("ix_ktp_wbs_items_session", "ktp_wbs_items", ["session_id"])
    op.create_index("ix_ktp_wbs_items_estimate", "ktp_wbs_items", ["estimate_id"])

    op.create_table(
        "ktp_wbs_group_dependencies",
        sa.Column(
            "group_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ktp_wbs_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_group_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ktp_wbs_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade():
    op.drop_table("ktp_wbs_group_dependencies")
    op.drop_index("ix_ktp_wbs_items_estimate", table_name="ktp_wbs_items")
    op.drop_index("ix_ktp_wbs_items_session", table_name="ktp_wbs_items")
    op.drop_index("ix_ktp_wbs_items_group", table_name="ktp_wbs_items")
    op.drop_table("ktp_wbs_items")
    op.drop_index("ix_ktp_wbs_groups_session", table_name="ktp_wbs_groups")
    op.drop_table("ktp_wbs_groups")
    op.drop_index(
        "ix_ktp_estimate_sessions_batch", table_name="ktp_estimate_sessions"
    )
    op.drop_table("ktp_estimate_sessions")
