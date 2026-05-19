"""Add clarification answers to estimate batches."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "047_est_batch_clarifications"
down_revision = "046_ktp_estimate_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "estimate_batches",
        sa.Column("clarification_answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("estimate_batches", "clarification_answers")
