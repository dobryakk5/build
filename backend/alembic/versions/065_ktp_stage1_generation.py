"""Add generation fence for KTP Stage 1 jobs."""

from __future__ import annotations

from alembic import op


revision = "065_ktp_stage1_generation"
down_revision = "064_ktp_rate_unit_conversion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_estimate_sessions
        ADD COLUMN IF NOT EXISTS stage1_generation integer NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ktp_estimate_sessions_stage1_job_generation
        ON ktp_estimate_sessions (stage1_job_id, stage1_generation)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_ktp_estimate_sessions_stage1_job_generation
        """
    )
    op.execute(
        """
        ALTER TABLE ktp_estimate_sessions
        DROP COLUMN IF EXISTS stage1_generation
        """
    )
