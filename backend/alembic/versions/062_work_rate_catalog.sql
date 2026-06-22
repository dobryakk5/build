-- Work-rate catalogue schema for PostgreSQL.
-- Apply through the project's Alembic wrapper; the source archive did not
-- contain its migration environment, therefore this file is intentionally raw SQL.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS work_rate_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(255) NOT NULL,
    source_kind varchar(64) NOT NULL,
    source_file varchar(512) NOT NULL,
    source_sheet varchar(255),
    source_version varchar(64) NOT NULL DEFAULT '1',
    valid_from date,
    valid_to date,
    region varchar(255),
    currency char(3) NOT NULL DEFAULT 'RUB',
    hourly_rate numeric(18,4),
    labor_basis varchar(64),
    is_active boolean NOT NULL DEFAULT true,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_work_rate_source_kind CHECK (
        source_kind IN ('normalized_rate_catalog','market_estimate_observation','manual_catalog','external_normative')
    )
);

CREATE TABLE IF NOT EXISTS work_rate_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES work_rate_sources(id) ON DELETE CASCADE,
    source_row integer NOT NULL,
    external_code varchar(128),
    stable_row_key varchar(128) NOT NULL,
    row_content_hash varchar(128) NOT NULL,
    revision integer NOT NULL DEFAULT 1,
    supersedes_rate_item_id uuid REFERENCES work_rate_items(id),
    name text NOT NULL,
    normalized_name text NOT NULL,
    notes text,
    normalized_notes text,
    unit_raw varchar(128),
    unit_code varchar(64),
    unit_dimension varchar(64),
    quantity numeric(20,6),
    price_min numeric(20,6),
    price_max numeric(20,6),
    price_avg numeric(20,6),
    total_price numeric(20,6),
    labor_min numeric(20,6),
    labor_max numeric(20,6),
    labor_avg numeric(20,6),
    hourly_rate numeric(20,6),
    labor_basis varchar(64),
    mapping_status varchar(64) NOT NULL DEFAULT 'unmapped',
    has_active_mapping boolean NOT NULL DEFAULT false,
    is_package_candidate boolean NOT NULL DEFAULT false,
    review_status varchar(64) NOT NULL DEFAULT 'new',
    review_reason text,
    approved_as_rate boolean NOT NULL DEFAULT false,
    auto_applicable boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    row_role varchar(32) NOT NULL DEFAULT 'work',
    source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_work_rate_revision CHECK (revision > 0),
    CONSTRAINT ck_work_rate_price_range CHECK (
        (price_min IS NULL OR price_avg IS NULL OR price_min <= price_avg)
        AND (price_avg IS NULL OR price_max IS NULL OR price_avg <= price_max)
    ),
    CONSTRAINT ck_work_rate_labor_range CHECK (
        (labor_min IS NULL OR labor_avg IS NULL OR labor_min <= labor_avg)
        AND (labor_avg IS NULL OR labor_max IS NULL OR labor_avg <= labor_max)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_work_rate_item_revision
    ON work_rate_items(source_id, stable_row_key, revision);
CREATE INDEX IF NOT EXISTS ix_work_rate_item_active_name
    ON work_rate_items(is_active, normalized_name);
CREATE INDEX IF NOT EXISTS ix_work_rate_item_mapping_status
    ON work_rate_items(mapping_status, review_status);

CREATE TABLE IF NOT EXISTS work_rate_mappings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rate_item_id uuid NOT NULL REFERENCES work_rate_items(id) ON DELETE CASCADE,
    operation_code varchar(128),
    taxonomy_section_id varchar(128),
    taxonomy_subtype_id varchar(128),
    taxonomy_code varchar(260),
    object_scope_code varchar(128),
    mapping_mode varchar(32) NOT NULL,
    priority integer NOT NULL DEFAULT 100,
    confidence numeric(8,6) NOT NULL DEFAULT 0,
    mapping_source varchar(64) NOT NULL DEFAULT 'automatic',
    taxonomy_version varchar(128) NOT NULL,
    operation_policy_version varchar(64) NOT NULL,
    is_primary boolean NOT NULL DEFAULT true,
    is_active boolean NOT NULL DEFAULT true,
    approved_by uuid,
    approved_at timestamptz,
    included_operations jsonb NOT NULL DEFAULT '[]'::jsonb,
    diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_work_rate_mapping_mode CHECK (
        mapping_mode IN ('direct','contextual','package','excluded','observation','unmapped')
    ),
    CONSTRAINT ck_work_rate_mapping_confidence CHECK (confidence >= 0 AND confidence <= 1)
);
CREATE INDEX IF NOT EXISTS ix_work_rate_mapping_lookup
    ON work_rate_mappings(operation_code, taxonomy_code, object_scope_code)
    WHERE is_active;
CREATE INDEX IF NOT EXISTS ix_work_rate_mapping_item
    ON work_rate_mappings(rate_item_id, is_active);

CREATE TABLE IF NOT EXISTS work_rate_package_components (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_rate_item_id uuid NOT NULL REFERENCES work_rate_items(id) ON DELETE CASCADE,
    included_operation_code varchar(128) NOT NULL,
    included_taxonomy_code varchar(260),
    required boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(package_rate_item_id, included_operation_code, included_taxonomy_code)
);

CREATE TABLE IF NOT EXISTS work_rate_import_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid REFERENCES work_rate_sources(id),
    filename varchar(512) NOT NULL,
    file_hash varchar(128) NOT NULL,
    status varchar(64) NOT NULL,
    rows_total integer NOT NULL DEFAULT 0,
    rows_imported integer NOT NULL DEFAULT 0,
    rows_skipped integer NOT NULL DEFAULT 0,
    rows_created integer NOT NULL DEFAULT 0,
    rows_updated integer NOT NULL DEFAULT 0,
    rows_unmapped integer NOT NULL DEFAULT 0,
    rows_needs_review integer NOT NULL DEFAULT 0,
    errors_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    created_by uuid,
    UNIQUE(source_id, file_hash)
);

CREATE TABLE IF NOT EXISTS work_rate_unit_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alias varchar(128) NOT NULL UNIQUE,
    unit_code varchar(64) NOT NULL,
    unit_dimension varchar(64) NOT NULL,
    factor_to_base numeric(20,10) NOT NULL DEFAULT 1,
    is_active boolean NOT NULL DEFAULT true
);

-- Separate assignment table avoids assuming exact names of the project's KTP ORM tables.
CREATE TABLE IF NOT EXISTS work_rate_item_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid,
    ktp_item_id uuid NOT NULL,
    operation_code varchar(128),
    selected_rate_item_id uuid REFERENCES work_rate_items(id),
    selected_rate_mapping_id uuid REFERENCES work_rate_mappings(id),
    rate_selection_source varchar(64),
    rate_confidence numeric(8,6),
    rate_needs_review boolean NOT NULL DEFAULT false,
    rate_unit_code varchar(64),
    rate_price_min numeric(20,6),
    rate_price_max numeric(20,6),
    rate_price_avg numeric(20,6),
    labor_hours_per_unit_min numeric(20,6),
    labor_hours_per_unit_max numeric(20,6),
    labor_hours_per_unit_avg numeric(20,6),
    calculated_labor_hours_min numeric(20,6),
    calculated_labor_hours_max numeric(20,6),
    calculated_labor_hours_avg numeric(20,6),
    resolved_labor_hours numeric(20,6),
    resolved_labor_source varchar(64),
    labor_source_mode varchar(32),
    calculation_group_key varchar(128),
    package_resolution_mode varchar(32),
    rate_catalog_version varchar(64),
    rate_calculation_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(ktp_item_id)
);
CREATE INDEX IF NOT EXISTS ix_work_rate_assignment_group
    ON work_rate_item_assignments(calculation_group_key);

INSERT INTO work_rate_unit_aliases(alias, unit_code, unit_dimension, factor_to_base)
VALUES
 ('м2','m2','area',1), ('м²','m2','area',1), ('кв.м','m2','area',1),
 ('м3','m3','volume',1), ('м³','m3','volume',1), ('куб.м','m3','volume',1),
 ('мп','m','length',1), ('м.п.','m','length',1), ('пог.м','m','length',1),
 ('шт.','pcs','count',1), ('т','t','weight',1), ('кг','kg','weight',1),
 ('чел.-час','person_hour','time',1), ('маш.-час','machine_hour','machine_time',1),
 ('сотка','are','area_plot',1), ('смена','shift','time_scope',1),
 ('компл.','set','scope',1), ('точка','point','count_scope',1),
 ('проём','opening','count_scope',1), ('участок','site','scope',1),
 ('окно','window','count_scope',1), ('%','percent','ratio',1)
ON CONFLICT(alias) DO UPDATE SET
 unit_code = excluded.unit_code,
 unit_dimension = excluded.unit_dimension,
 factor_to_base = excluded.factor_to_base,
 is_active = true;
