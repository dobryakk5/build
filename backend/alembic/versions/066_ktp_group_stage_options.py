"""Persist confirmed semantic stage options on KTP WBS groups."""

from __future__ import annotations

from alembic import op


revision = "066_ktp_group_stage_options"
down_revision = "065_ktp_stage1_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_wbs_groups
            ADD COLUMN IF NOT EXISTS semantic_stage_option_id varchar(128),
            ADD COLUMN IF NOT EXISTS semantic_stage_option_title text,
            ADD COLUMN IF NOT EXISTS stage_option_source varchar(64),
            ADD COLUMN IF NOT EXISTS execution_applicability varchar(32)
                NOT NULL DEFAULT 'applicable';
        """
    )
    op.execute(
        """
        ALTER TABLE ktp_wbs_groups
            DROP CONSTRAINT IF EXISTS ck_ktp_wbs_groups_execution_applicability;
        """
    )
    op.execute(
        """
        ALTER TABLE ktp_wbs_groups
            ADD CONSTRAINT ck_ktp_wbs_groups_execution_applicability
            CHECK (execution_applicability IN ('applicable', 'not_applicable'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_wbs_groups
            DROP CONSTRAINT IF EXISTS ck_ktp_wbs_groups_execution_applicability;
        """
    )
    op.execute(
        """
        ALTER TABLE ktp_wbs_groups
            DROP COLUMN IF EXISTS execution_applicability,
            DROP COLUMN IF EXISTS stage_option_source,
            DROP COLUMN IF EXISTS semantic_stage_option_title,
            DROP COLUMN IF EXISTS semantic_stage_option_id;
        """
    )
