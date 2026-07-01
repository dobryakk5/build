"""Add stable public codes to locked KTP WBS groups."""

from __future__ import annotations

from alembic import op


revision = "068_ktp_wbs_code"
down_revision = "067_projection_status_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_wbs_groups
            ADD COLUMN IF NOT EXISTS wbs_code varchar(64);

        WITH catalog_codes AS (
            SELECT
                g.id,
                g.template_stage_number AS wbs_code
            FROM ktp_wbs_groups AS g
            JOIN ktp_estimate_sessions AS s ON s.id = g.session_id
            JOIN estimate_batches AS b ON b.id = s.estimate_batch_id
            WHERE g.execution_applicability = 'applicable'
              AND COALESCE(
                    NULLIF(b.project_variant_number, ''),
                    b.taxonomy_snapshot -> 'variant' ->> 'number',
                    ''
                  ) = '2.7'
              AND COALESCE(
                    b.taxonomy_snapshot -> 'variant' -> 'wbs_sequence_schema' ->> 'mode',
                    ''
                  ) = 'locked'
        )
        UPDATE ktp_wbs_groups AS g
        SET wbs_code = catalog_codes.wbs_code
        FROM catalog_codes
        WHERE g.id = catalog_codes.id
          AND catalog_codes.wbs_code ~ '^2[.]7[.][0-9]+$'
          AND g.wbs_code IS DISTINCT FROM catalog_codes.wbs_code;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ktp_wbs_groups DROP COLUMN IF EXISTS wbs_code;
        """
    )
