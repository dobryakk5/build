"""Create user activity event log."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "048_user_activity_events"
down_revision = "047_est_batch_clarifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_activity_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_user_activity_events_project_time",
        "user_activity_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "idx_user_activity_events_user_time",
        "user_activity_events",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_user_activity_events_event_type",
        "user_activity_events",
        ["event_type"],
    )


def downgrade():
    op.drop_index("idx_user_activity_events_event_type", table_name="user_activity_events")
    op.drop_index("idx_user_activity_events_user_time", table_name="user_activity_events")
    op.drop_index("idx_user_activity_events_project_time", table_name="user_activity_events")
    op.drop_table("user_activity_events")
