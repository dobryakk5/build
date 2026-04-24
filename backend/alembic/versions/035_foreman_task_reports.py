from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "035_foreman_task_reports"
down_revision = "034_update_seed_test_credentials"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "foreman_task_reports",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            UUID(as_uuid=False),
            sa.ForeignKey("gantt_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "foreman_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("token", sa.String(512), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("email_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("responded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_ftr_project_date",
        "foreman_task_reports",
        ["project_id", "report_date"],
    )
    op.create_index(
        "idx_ftr_foreman_date",
        "foreman_task_reports",
        ["foreman_id", "report_date"],
    )
    op.create_index(
        "idx_ftr_token",
        "foreman_task_reports",
        ["token"],
        unique=True,
    )


def downgrade():
    op.drop_table("foreman_task_reports")
