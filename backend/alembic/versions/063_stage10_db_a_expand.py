"""Stage 10 DB-A expand for variant 2.7 post-release contour."""

from __future__ import annotations

from alembic import op


revision = "063_stage10_db_a_expand"
down_revision = "062_work_rate_catalog"
branch_labels = None
depends_on = None


def _execute_sql_script(sql: str) -> None:
    without_line_comments = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    for statement in without_line_comments.split(";"):
        stripped = statement.strip()
        if stripped:
            op.execute(stripped)


def upgrade() -> None:
    _execute_sql_script(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        ALTER TABLE work_rate_mappings
            ADD COLUMN IF NOT EXISTS rate_context_code varchar(64);
        CREATE INDEX IF NOT EXISTS ix_work_rate_mappings_rate_context_code
            ON work_rate_mappings(rate_context_code);

        ALTER TABLE work_rate_items
            ADD COLUMN IF NOT EXISTS norm_base_quantity numeric(20,6),
            ADD COLUMN IF NOT EXISTS source_rate_id varchar(128),
            ADD COLUMN IF NOT EXISTS rate_value_mode varchar(64),
            ADD COLUMN IF NOT EXISTS resolution_status varchar(64),
            ADD COLUMN IF NOT EXISTS applicability_json jsonb;

        ALTER TABLE estimate_batches
            ADD COLUMN IF NOT EXISTS building_params jsonb,
            ADD COLUMN IF NOT EXISTS project_structure_options jsonb,
            ADD COLUMN IF NOT EXISTS applicability_hash_version smallint,
            ADD COLUMN IF NOT EXISTS applicability_schema_version varchar(64),
            ADD COLUMN IF NOT EXISTS source_row_scope_version smallint,
            ADD COLUMN IF NOT EXISTS source_row_scope_migration_status varchar(32),
            ADD COLUMN IF NOT EXISTS source_row_scope_migration_failure_code varchar(128),
            ADD COLUMN IF NOT EXISTS source_row_scope_migration_failure_details jsonb,
            ADD COLUMN IF NOT EXISTS calculation_status varchar(32),
            ADD COLUMN IF NOT EXISTS calculation_block_reason varchar(128),
            ADD COLUMN IF NOT EXISTS import_status varchar(32),
            ADD COLUMN IF NOT EXISTS supersedes_batch_id uuid,
            ADD COLUMN IF NOT EXISTS is_active boolean,
            ADD COLUMN IF NOT EXISTS taxonomy_snapshot jsonb,
            ADD COLUMN IF NOT EXISTS variant_schema_version varchar(128),
            ADD COLUMN IF NOT EXISTS taxonomy_resolution_mode varchar(64),
            ADD COLUMN IF NOT EXISTS taxonomy_locked boolean,
            ADD COLUMN IF NOT EXISTS work_rate_catalog_version varchar(64),
            ADD COLUMN IF NOT EXISTS work_rate_catalog_hash varchar(128),
            ADD COLUMN IF NOT EXISTS projection_generation_status varchar(32),
            ADD COLUMN IF NOT EXISTS projection_failure_code varchar(128),
            ADD COLUMN IF NOT EXISTS projection_failure_details jsonb,
            ADD COLUMN IF NOT EXISTS revalidated_at timestamptz,
            ADD COLUMN IF NOT EXISTS revalidated_by_user_id uuid;

        CREATE INDEX IF NOT EXISTS ix_estimate_batches_calculation_status
            ON estimate_batches(calculation_status);
        CREATE INDEX IF NOT EXISTS ix_estimate_batches_import_status
            ON estimate_batches(import_status);
        CREATE INDEX IF NOT EXISTS ix_estimate_batches_scope_migration_status
            ON estimate_batches(source_row_scope_migration_status);
        CREATE INDEX IF NOT EXISTS ix_estimate_batches_active_variant
            ON estimate_batches(project_variant_id, is_active)
            WHERE is_active IS TRUE;

        ALTER TABLE estimates
            ADD COLUMN IF NOT EXISTS stage_instance_id varchar(255),
            ADD COLUMN IF NOT EXISTS template_stage_number varchar(64),
            ADD COLUMN IF NOT EXISTS floor_number integer,
            ADD COLUMN IF NOT EXISTS floor_kind varchar(32),
            ADD COLUMN IF NOT EXISTS floor_label varchar(128),
            ADD COLUMN IF NOT EXISTS floor_component varchar(64),
            ADD COLUMN IF NOT EXISTS component_role varchar(128),
            ADD COLUMN IF NOT EXISTS source_row_key uuid,
            ADD COLUMN IF NOT EXISTS source_scope_id uuid,
            ADD COLUMN IF NOT EXISTS work_scope_key varchar(255),
            ADD COLUMN IF NOT EXISTS legacy_work_scope_key varchar(255),
            ADD COLUMN IF NOT EXISTS applicability jsonb,
            ADD COLUMN IF NOT EXISTS applicability_hash char(64),
            ADD COLUMN IF NOT EXISTS applicability_hash_version smallint,
            ADD COLUMN IF NOT EXISTS applicability_schema_version varchar(64),
            ADD COLUMN IF NOT EXISTS stage_option_source varchar(64),
            ADD COLUMN IF NOT EXISTS taxonomy_snapshot jsonb,
            ADD COLUMN IF NOT EXISTS taxonomy_locked boolean,
            ADD COLUMN IF NOT EXISTS variant_schema_version varchar(128),
            ADD COLUMN IF NOT EXISTS classification_migrated_from_version varchar(255),
            ADD COLUMN IF NOT EXISTS classification_migrated_to_version varchar(255),
            ADD COLUMN IF NOT EXISTS classification_migrated_at timestamptz,
            ADD COLUMN IF NOT EXISTS calculation_trace jsonb,
            ADD COLUMN IF NOT EXISTS projection_json jsonb;

        CREATE INDEX IF NOT EXISTS ix_estimates_batch_stage_instance
            ON estimates(estimate_batch_id, stage_instance_id);
        CREATE INDEX IF NOT EXISTS ix_estimates_batch_floor
            ON estimates(estimate_batch_id, floor_number);
        CREATE INDEX IF NOT EXISTS ix_estimates_batch_source_row_key
            ON estimates(estimate_batch_id, source_row_key);
        CREATE INDEX IF NOT EXISTS ix_estimates_batch_work_scope_key
            ON estimates(estimate_batch_id, work_scope_key);
        CREATE INDEX IF NOT EXISTS ix_estimates_batch_applicability_version
            ON estimates(estimate_batch_id, applicability_hash_version);

        ALTER TABLE gantt_tasks
            ADD COLUMN IF NOT EXISTS task_kind varchar(32),
            ADD COLUMN IF NOT EXISTS source_row_key uuid,
            ADD COLUMN IF NOT EXISTS projection_id varchar(96),
            ADD COLUMN IF NOT EXISTS stage_instance_id varchar(255),
            ADD COLUMN IF NOT EXISTS template_stage_number varchar(64),
            ADD COLUMN IF NOT EXISTS stage_number varchar(64),
            ADD COLUMN IF NOT EXISTS canonical_stage_id varchar(255),
            ADD COLUMN IF NOT EXISTS floor_number integer,
            ADD COLUMN IF NOT EXISTS floor_kind varchar(32),
            ADD COLUMN IF NOT EXISTS floor_label varchar(128),
            ADD COLUMN IF NOT EXISTS floor_component varchar(64),
            ADD COLUMN IF NOT EXISTS component_role varchar(128),
            ADD COLUMN IF NOT EXISTS operation_code varchar(128),
            ADD COLUMN IF NOT EXISTS operation_package_code varchar(128),
            ADD COLUMN IF NOT EXISTS semantic_stage_option_id varchar(128),
            ADD COLUMN IF NOT EXISTS stage_option_source varchar(64),
            ADD COLUMN IF NOT EXISTS work_scope_key varchar(255),
            ADD COLUMN IF NOT EXISTS applicability_hash char(64),
            ADD COLUMN IF NOT EXISTS applicability_hash_version smallint,
            ADD COLUMN IF NOT EXISTS applicability_schema_version varchar(64),
            ADD COLUMN IF NOT EXISTS projection_metadata jsonb;

        CREATE INDEX IF NOT EXISTS ix_gantt_tasks_stage_instance
            ON gantt_tasks(estimate_batch_id, stage_instance_id);
        CREATE INDEX IF NOT EXISTS ix_gantt_tasks_lineage
            ON gantt_tasks(estimate_batch_id, source_row_key, projection_id);
        CREATE INDEX IF NOT EXISTS ix_gantt_tasks_structural_completion
            ON gantt_tasks(estimate_batch_id, stage_instance_id)
            WHERE task_kind = 'milestone';

        ALTER TABLE ktp_wbs_groups
            ADD COLUMN IF NOT EXISTS stage_instance_id varchar(255),
            ADD COLUMN IF NOT EXISTS template_stage_number varchar(64),
            ADD COLUMN IF NOT EXISTS stage_number varchar(64),
            ADD COLUMN IF NOT EXISTS floor_number integer,
            ADD COLUMN IF NOT EXISTS floor_kind varchar(32),
            ADD COLUMN IF NOT EXISTS floor_label varchar(128),
            ADD COLUMN IF NOT EXISTS floor_component varchar(64),
            ADD COLUMN IF NOT EXISTS component_role varchar(128);

        CREATE INDEX IF NOT EXISTS ix_ktp_wbs_groups_stage_instance
            ON ktp_wbs_groups(session_id, stage_instance_id);

        ALTER TABLE ktp_wbs_items
            ADD COLUMN IF NOT EXISTS source_row_key uuid,
            ADD COLUMN IF NOT EXISTS projection_id varchar(96),
            ADD COLUMN IF NOT EXISTS stage_instance_id varchar(255),
            ADD COLUMN IF NOT EXISTS template_stage_number varchar(64),
            ADD COLUMN IF NOT EXISTS stage_number varchar(64),
            ADD COLUMN IF NOT EXISTS floor_number integer,
            ADD COLUMN IF NOT EXISTS floor_kind varchar(32),
            ADD COLUMN IF NOT EXISTS floor_label varchar(128),
            ADD COLUMN IF NOT EXISTS floor_component varchar(64),
            ADD COLUMN IF NOT EXISTS component_role varchar(128),
            ADD COLUMN IF NOT EXISTS operation_code varchar(128),
            ADD COLUMN IF NOT EXISTS operation_package_code varchar(128),
            ADD COLUMN IF NOT EXISTS semantic_stage_option_id varchar(128),
            ADD COLUMN IF NOT EXISTS stage_option_source varchar(64),
            ADD COLUMN IF NOT EXISTS work_scope_key varchar(255),
            ADD COLUMN IF NOT EXISTS applicability_hash char(64),
            ADD COLUMN IF NOT EXISTS applicability_hash_version smallint,
            ADD COLUMN IF NOT EXISTS applicability_schema_version varchar(64),
            ADD COLUMN IF NOT EXISTS duration_block_reason varchar(128);

        CREATE INDEX IF NOT EXISTS ix_ktp_wbs_items_lineage
            ON ktp_wbs_items(session_id, source_row_key, projection_id);

        CREATE TABLE IF NOT EXISTS estimate_preview_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_user_id uuid NOT NULL REFERENCES users(id),
            project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
            project_variant_id varchar(255) NOT NULL,
            taxonomy_dictionary_version varchar(255) NOT NULL,
            building_params jsonb NOT NULL,
            project_structure_options jsonb NOT NULL DEFAULT '{}'::jsonb,
            source_file_fingerprint_algorithm varchar(16) NOT NULL DEFAULT 'sha256',
            source_file_fingerprint char(64) NOT NULL,
            source_file_size_bytes bigint NOT NULL,
            status varchar(32) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            processing_deadline_at timestamptz NOT NULL,
            activated_at timestamptz,
            expires_at timestamptz,
            confirmed_at timestamptz,
            cancelled_at timestamptz,
            expired_at timestamptz,
            failed_at timestamptz,
            confirming_started_at timestamptz,
            confirming_attempt_count integer NOT NULL DEFAULT 0,
            failure_code varchar(128),
            failure_details jsonb,
            estimate_batch_id uuid UNIQUE REFERENCES estimate_batches(id),
            snapshot_payload_version smallint,
            snapshot_hash_algorithm varchar(16),
            snapshot_hash char(64),
            snapshot_payload jsonb,
            snapshot_purged_at timestamptz,
            preview_content_hash_payload_version smallint NOT NULL DEFAULT 1,
            preview_content_hash_algorithm varchar(16) NOT NULL DEFAULT 'sha256',
            preview_content_hash char(64),
            CONSTRAINT ck_estimate_preview_session_status CHECK (
                status IN ('processing','active','confirming','confirmed','expired','cancelled','failed')
            ),
            CONSTRAINT ck_estimate_preview_source_file_size CHECK (source_file_size_bytes > 0),
            CONSTRAINT ck_estimate_preview_fingerprint_algorithm CHECK (
                source_file_fingerprint_algorithm = 'sha256'
            )
        );

        CREATE INDEX IF NOT EXISTS ix_estimate_preview_sessions_owner_created
            ON estimate_preview_sessions(owner_user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_estimate_preview_sessions_status_deadline
            ON estimate_preview_sessions(status, processing_deadline_at);
        CREATE INDEX IF NOT EXISTS ix_estimate_preview_sessions_status_expires
            ON estimate_preview_sessions(status, expires_at);

        CREATE TABLE IF NOT EXISTS estimate_preview_rows (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            preview_session_id uuid NOT NULL REFERENCES estimate_preview_sessions(id) ON DELETE CASCADE,
            source_row_key uuid NOT NULL,
            source_scope_id uuid,
            source_row_index integer NOT NULL,
            source_text text NOT NULL,
            parsed_data jsonb NOT NULL,
            classification_result jsonb NOT NULL,
            confirmation_approved boolean,
            confirmation_manual_override jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_estimate_preview_rows_session_source_row
                UNIQUE(preview_session_id, source_row_key),
            CONSTRAINT ck_estimate_preview_row_index CHECK (source_row_index >= 0)
        );
        CREATE INDEX IF NOT EXISTS ix_estimate_preview_rows_session_order
            ON estimate_preview_rows(preview_session_id, source_row_index, source_row_key);

        CREATE TABLE IF NOT EXISTS transactional_outbox (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            aggregate_type varchar(128) NOT NULL,
            aggregate_id uuid NOT NULL,
            event_type varchar(128) NOT NULL,
            idempotency_key varchar(512) NOT NULL UNIQUE,
            payload jsonb NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'pending',
            attempt_count integer NOT NULL DEFAULT 0,
            next_attempt_at timestamptz,
            last_error_code varchar(128),
            last_error_details jsonb,
            published_at timestamptz,
            dead_lettered_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_transactional_outbox_status CHECK (
                status IN ('pending','publishing','published','dead_letter')
            ),
            CONSTRAINT ck_transactional_outbox_attempt_count CHECK (attempt_count >= 0)
        );
        CREATE INDEX IF NOT EXISTS ix_transactional_outbox_delivery
            ON transactional_outbox(status, next_attempt_at, created_at)
            WHERE status IN ('pending','publishing');
        CREATE INDEX IF NOT EXISTS ix_transactional_outbox_aggregate
            ON transactional_outbox(aggregate_type, aggregate_id);

        CREATE TABLE IF NOT EXISTS estimate_import_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            preview_session_id uuid NOT NULL REFERENCES estimate_preview_sessions(id),
            estimate_batch_id uuid NOT NULL REFERENCES estimate_batches(id),
            outbox_record_id uuid REFERENCES transactional_outbox(id),
            idempotency_key varchar(512) NOT NULL UNIQUE,
            status varchar(32) NOT NULL DEFAULT 'queued',
            reason_code varchar(128),
            reason_details jsonb,
            attempt_count integer NOT NULL DEFAULT 0,
            next_attempt_at timestamptz,
            snapshot_payload_version smallint,
            snapshot_hash_algorithm varchar(16),
            snapshot_hash char(64),
            worker_id varchar(255),
            queued_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_estimate_import_job_status CHECK (
                status IN ('queued','running','retrying','completed','failed','blocked')
            ),
            CONSTRAINT ck_estimate_import_job_attempt_count CHECK (attempt_count >= 0)
        );
        CREATE INDEX IF NOT EXISTS ix_estimate_import_jobs_status_retry
            ON estimate_import_jobs(status, next_attempt_at, queued_at);
        CREATE INDEX IF NOT EXISTS ix_estimate_import_jobs_batch
            ON estimate_import_jobs(estimate_batch_id);

        CREATE TABLE IF NOT EXISTS estimate_quantity_projections (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            estimate_batch_id uuid NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
            estimate_id uuid REFERENCES estimates(id) ON DELETE CASCADE,
            source_row_key uuid,
            projection_id varchar(96),
            stage_instance_id varchar(255),
            operation_code varchar(128),
            operation_package_code varchar(128),
            semantic_stage_option_id varchar(128),
            work_scope_key varchar(255),
            applicability jsonb,
            applicability_hash char(64),
            applicability_hash_version smallint,
            applicability_schema_version varchar(64),
            quantity numeric(20,6),
            unit_code varchar(64),
            resolution_status varchar(64),
            reason_code varchar(128),
            metadata_json jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_estimate_quantity_projections_batch
            ON estimate_quantity_projections(estimate_batch_id, stage_instance_id);

        CREATE TABLE IF NOT EXISTS estimate_package_resolutions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            estimate_batch_id uuid NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
            estimate_id uuid REFERENCES estimates(id) ON DELETE CASCADE,
            source_row_key uuid,
            work_scope_key varchar(255),
            applicability_hash char(64),
            applicability_hash_version smallint,
            resolution_status varchar(64),
            resolution_payload jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_estimate_package_resolutions_batch
            ON estimate_package_resolutions(estimate_batch_id, source_row_key);

        CREATE TABLE IF NOT EXISTS stage_instance_projection_summaries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            estimate_batch_id uuid NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
            stage_instance_id varchar(255) NOT NULL,
            projection_generation_status varchar(32) NOT NULL,
            failure_code varchar(128),
            metadata_json jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_stage_instance_projection_summaries_batch
            ON stage_instance_projection_summaries(estimate_batch_id, stage_instance_id);

        CREATE TABLE IF NOT EXISTS legacy_scope_migration_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            estimate_batch_id uuid NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
            source_contract_version smallint NOT NULL,
            target_contract_version smallint NOT NULL,
            json_path_registry_version varchar(96) NOT NULL,
            status varchar(32) NOT NULL,
            attempt_count integer NOT NULL DEFAULT 0,
            migrated_estimate_count integer NOT NULL DEFAULT 0,
            updated_record_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
            failure_code varchar(128),
            failure_details jsonb,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz
        );
        CREATE INDEX IF NOT EXISTS ix_legacy_scope_migration_runs_batch_started
            ON legacy_scope_migration_runs(estimate_batch_id, started_at DESC);

        CREATE TABLE IF NOT EXISTS estimate_batch_revalidation_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            estimate_batch_id uuid NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
            requested_by_user_id uuid NOT NULL REFERENCES users(id),
            permission_code varchar(96) NOT NULL,
            previous_calculation_status varchar(32) NOT NULL,
            result_calculation_status varchar(32) NOT NULL,
            blocking_reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
            review_reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
            import_command_requeued boolean NOT NULL DEFAULT false,
            import_job_id uuid REFERENCES estimate_import_jobs(id),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_estimate_batch_revalidation_runs_batch_created
            ON estimate_batch_revalidation_runs(estimate_batch_id, created_at DESC);
        """
    )


def downgrade() -> None:
    # DB-A downgrade intentionally removes only the new stage-10 tables. Nullable
    # columns on legacy tables are left in place to avoid destructive data loss.
    _execute_sql_script(
        """
        DROP TABLE IF EXISTS estimate_batch_revalidation_runs;
        DROP TABLE IF EXISTS legacy_scope_migration_runs;
        DROP TABLE IF EXISTS stage_instance_projection_summaries;
        DROP TABLE IF EXISTS estimate_package_resolutions;
        DROP TABLE IF EXISTS estimate_quantity_projections;
        DROP TABLE IF EXISTS estimate_import_jobs;
        DROP TABLE IF EXISTS transactional_outbox;
        DROP TABLE IF EXISTS estimate_preview_rows;
        DROP TABLE IF EXISTS estimate_preview_sessions;
        """
    )
