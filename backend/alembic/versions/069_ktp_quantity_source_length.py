"""Allow all KTP quantity projection source values."""

from __future__ import annotations

from alembic import op


revision = "069_ktp_quantity_source_length"
down_revision = "068_ktp_wbs_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_wbs_items
            ALTER COLUMN quantity_source TYPE varchar(32)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ktp_wbs_items
        SET quantity_source = NULL
        WHERE length(quantity_source) > 16
        """
    )
    op.execute(
        """
        ALTER TABLE ktp_wbs_items
            ALTER COLUMN quantity_source TYPE varchar(16)
        """
    )
