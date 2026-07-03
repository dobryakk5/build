"""Add immutable estimate-batch rate owners and personal work rates."""

from __future__ import annotations

from alembic import op


revision = "070_user_work_rates"
down_revision = "069_ktp_quantity_source_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE estimate_batches
            ADD COLUMN rate_owner_user_id uuid
        """
    )
    # A clean migration chain still contains batches materialized by migration
    # 014 from the seed estimates. Their project creator is the only owner.
    op.execute(
        """
        UPDATE estimate_batches AS batch
        SET rate_owner_user_id = project.created_by
        FROM projects AS project
        WHERE project.id = batch.project_id
          AND batch.rate_owner_user_id IS NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM estimate_batches
                WHERE rate_owner_user_id IS NULL
            ) THEN
                RAISE EXCEPTION 'rate_owner_user_id_required';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE estimate_batches
            ALTER COLUMN rate_owner_user_id SET NOT NULL,
            ADD CONSTRAINT fk_estimate_batches_rate_owner_user_id
                FOREIGN KEY (rate_owner_user_id)
                REFERENCES users(id) ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        CREATE INDEX ix_estimate_batches_rate_owner_user_id
            ON estimate_batches (rate_owner_user_id)
        """
    )
    op.execute(
        """
        CREATE TABLE user_work_rates (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            taxonomy_code text NOT NULL,
            operation_code text NOT NULL,
            object_scope_code text NULL,
            rate_context_code text NULL,
            rate_variant_code text NULL,
            unit_code varchar(32) NOT NULL,
            labor_hours_per_unit numeric(18, 6) NOT NULL,
            work_name_snapshot text NOT NULL,
            source_estimate_batch_id uuid NULL
                REFERENCES estimate_batches(id) ON DELETE SET NULL,
            source_estimate_row_id uuid NULL
                REFERENCES estimates(id) ON DELETE SET NULL,
            taxonomy_version_at_creation varchar(128) NULL,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_user_work_rates_labor_positive
                CHECK (labor_hours_per_unit > 0)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_user_work_rates_match_key
            ON user_work_rates (
                user_id,
                taxonomy_code,
                operation_code,
                object_scope_code,
                rate_context_code,
                rate_variant_code,
                unit_code
            ) NULLS NOT DISTINCT
        """
    )
    op.execute(
        """
        CREATE INDEX ix_user_work_rates_user_active
            ON user_work_rates (user_id, is_active)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_user_work_rates_lookup
            ON user_work_rates (
                user_id, taxonomy_code, operation_code, unit_code
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE user_work_rates")
    op.execute("DROP INDEX ix_estimate_batches_rate_owner_user_id")
    op.execute(
        "ALTER TABLE estimate_batches DROP COLUMN rate_owner_user_id"
    )
