from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

TIMESTAMPTZ = TIMESTAMP(timezone=True)


def _uuid() -> str:
    return str(uuid.uuid4())


class EstimatePreviewSession(Base):
    __tablename__ = "estimate_preview_sessions"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    project_variant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    taxonomy_dictionary_version: Mapped[str] = mapped_column(String(255), nullable=False)
    building_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    project_structure_options: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_file_fingerprint_algorithm: Mapped[str] = mapped_column(String(16), nullable=False, default="sha256")
    source_file_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    processing_deadline_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    cancelled_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    expired_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    failed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    confirming_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    confirming_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_details: Mapped[dict | None] = mapped_column(JSONB)
    estimate_batch_id: Mapped[str | None] = mapped_column(ForeignKey("estimate_batches.id"))
    snapshot_payload_version: Mapped[int | None] = mapped_column(SmallInteger)
    snapshot_hash_algorithm: Mapped[str | None] = mapped_column(String(16))
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot_payload: Mapped[dict | None] = mapped_column(JSONB)
    snapshot_purged_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    preview_content_hash_payload_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    preview_content_hash_algorithm: Mapped[str] = mapped_column(String(16), nullable=False, default="sha256")
    preview_content_hash: Mapped[str | None] = mapped_column(String(64))


class EstimatePreviewRow(Base):
    __tablename__ = "estimate_preview_rows"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    preview_session_id: Mapped[str] = mapped_column(ForeignKey("estimate_preview_sessions.id", ondelete="CASCADE"), nullable=False)
    source_row_key: Mapped[str] = mapped_column(PGUUID(as_uuid=False), nullable=False)
    source_scope_id: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    source_row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    classification_result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confirmation_approved: Mapped[bool | None] = mapped_column(Boolean)
    confirmation_manual_override: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)


class TransactionalOutbox(Base):
    __tablename__ = "transactional_outbox"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_error_details: Mapped[dict | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)


class EstimateImportJob(Base):
    __tablename__ = "estimate_import_jobs"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    preview_session_id: Mapped[str] = mapped_column(ForeignKey("estimate_preview_sessions.id"), nullable=False)
    estimate_batch_id: Mapped[str] = mapped_column(ForeignKey("estimate_batches.id"), nullable=False)
    outbox_record_id: Mapped[str | None] = mapped_column(ForeignKey("transactional_outbox.id"))
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    reason_code: Mapped[str | None] = mapped_column(String(128))
    reason_details: Mapped[dict | None] = mapped_column(JSONB)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    snapshot_payload_version: Mapped[int | None] = mapped_column(SmallInteger)
    snapshot_hash_algorithm: Mapped[str | None] = mapped_column(String(16))
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    worker_id: Mapped[str | None] = mapped_column(String(255))
    queued_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)


class EstimateQuantityProjection(Base):
    __tablename__ = "estimate_quantity_projections"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    estimate_batch_id: Mapped[str] = mapped_column(ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False)
    estimate_id: Mapped[str | None] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"))
    source_row_key: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    projection_id: Mapped[str | None] = mapped_column(String(96))
    stage_instance_id: Mapped[str | None] = mapped_column(String(255))
    operation_code: Mapped[str | None] = mapped_column(String(128))
    operation_package_code: Mapped[str | None] = mapped_column(String(128))
    semantic_stage_option_id: Mapped[str | None] = mapped_column(String(128))
    work_scope_key: Mapped[str | None] = mapped_column(String(255))
    applicability: Mapped[dict | None] = mapped_column(JSONB)
    applicability_hash: Mapped[str | None] = mapped_column(String(64))
    applicability_hash_version: Mapped[int | None] = mapped_column(SmallInteger)
    applicability_schema_version: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[float | None] = mapped_column(Numeric(20, 6))
    unit_code: Mapped[str | None] = mapped_column(String(64))
    resolution_status: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)


class EstimatePackageResolution(Base):
    __tablename__ = "estimate_package_resolutions"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    estimate_batch_id: Mapped[str] = mapped_column(ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False)
    estimate_id: Mapped[str | None] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"))
    source_row_key: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    work_scope_key: Mapped[str | None] = mapped_column(String(255))
    applicability_hash: Mapped[str | None] = mapped_column(String(64))
    applicability_hash_version: Mapped[int | None] = mapped_column(SmallInteger)
    resolution_status: Mapped[str | None] = mapped_column(String(64))
    resolution_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)


class StageInstanceProjectionSummary(Base):
    __tablename__ = "stage_instance_projection_summaries"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    estimate_batch_id: Mapped[str] = mapped_column(ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False)
    stage_instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    projection_generation_status: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)


class LegacyScopeMigrationRun(Base):
    __tablename__ = "legacy_scope_migration_runs"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    estimate_batch_id: Mapped[str] = mapped_column(ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False)
    source_contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    json_path_registry_version: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    migrated_estimate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_record_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_details: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class EstimateBatchRevalidationRun(Base):
    __tablename__ = "estimate_batch_revalidation_runs"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=_uuid)
    estimate_batch_id: Mapped[str] = mapped_column(ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    permission_code: Mapped[str] = mapped_column(String(96), nullable=False)
    previous_calculation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_calculation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    blocking_reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    review_reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    import_command_requeued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    import_job_id: Mapped[str | None] = mapped_column(ForeignKey("estimate_import_jobs.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
