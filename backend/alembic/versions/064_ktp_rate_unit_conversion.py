"""Persist user-confirmed rate unit conversions for KTP productivity."""

from __future__ import annotations

from alembic import op


revision = "064_ktp_rate_unit_conversion"
down_revision = "063_stage10_db_a_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_session_subtypes
        ADD COLUMN IF NOT EXISTS rate_unit_conversion JSONB
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_session_subtypes
        DROP COLUMN IF EXISTS rate_unit_conversion
        """
    )
