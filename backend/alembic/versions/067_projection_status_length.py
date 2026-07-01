"""Allow all semantic projection-generation status values."""

from __future__ import annotations

from alembic import op


revision = "067_projection_status_length"
down_revision = "066_ktp_group_stage_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE stage_instance_projection_summaries
            ALTER COLUMN projection_generation_status TYPE varchar(64);
        ALTER TABLE estimate_batches
            ALTER COLUMN projection_generation_status TYPE varchar(64);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE stage_instance_projection_summaries
        SET projection_generation_status = 'blocked'
        WHERE length(projection_generation_status) > 32;
        UPDATE estimate_batches
        SET projection_generation_status = 'blocked'
        WHERE length(projection_generation_status) > 32;
        ALTER TABLE stage_instance_projection_summaries
            ALTER COLUMN projection_generation_status TYPE varchar(32);
        ALTER TABLE estimate_batches
            ALTER COLUMN projection_generation_status TYPE varchar(32);
        """
    )
