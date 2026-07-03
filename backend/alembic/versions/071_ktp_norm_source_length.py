"""Allow canonical work-rate source names on KTP WBS items."""

from __future__ import annotations

from alembic import op


revision = "071_ktp_norm_source_length"
down_revision = "070_user_work_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_wbs_items
            ALTER COLUMN norm_source TYPE varchar(32)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ktp_wbs_items
        SET norm_source = NULL
        WHERE length(norm_source) > 8
        """
    )
    op.execute(
        """
        ALTER TABLE ktp_wbs_items
            ALTER COLUMN norm_source TYPE varchar(8)
        """
    )
