"""Persist user-confirmed rate unit conversions for KTP productivity."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "064_ktp_rate_unit_conversion"
down_revision = "063_stage10_db_a_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ktp_session_subtypes",
        sa.Column("rate_unit_conversion", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ktp_session_subtypes", "rate_unit_conversion")
