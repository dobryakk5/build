from datetime import date, datetime
import uuid

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy import TIMESTAMP
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class EstimateBatch(Base, SoftDeleteMixin):
    __tablename__ = "estimate_batches"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    rate_owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    estimate_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    workers_count: Mapped[int | None] = mapped_column(SmallInteger)
    hours_per_day: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, server_default=sa_text("8"))
    source_filename: Mapped[str | None] = mapped_column(Text)
    estimate_type_id: Mapped[str | None] = mapped_column(Text)
    estimate_type_title: Mapped[str | None] = mapped_column(Text)
    estimate_type_number: Mapped[str | None] = mapped_column(String(16))
    project_variant_id: Mapped[str | None] = mapped_column(Text)
    project_variant_title: Mapped[str | None] = mapped_column(Text)
    project_variant_number: Mapped[str | None] = mapped_column(String(16))
    taxonomy_dictionary_version: Mapped[str | None] = mapped_column(String(128))
    clarification_answers: Mapped[dict | None] = mapped_column(JSONB)
    parser_profile: Mapped[str | None] = mapped_column(String(64))
    import_meta: Mapped[dict | None] = mapped_column(JSONB)
    building_params: Mapped[dict | None] = mapped_column(JSONB)
    project_structure_options: Mapped[dict | None] = mapped_column(JSONB)
    applicability_hash_version: Mapped[int | None] = mapped_column(SmallInteger)
    applicability_schema_version: Mapped[str | None] = mapped_column(String(64))
    source_row_scope_version: Mapped[int | None] = mapped_column(SmallInteger)
    source_row_scope_migration_status: Mapped[str | None] = mapped_column(String(32))
    source_row_scope_migration_failure_code: Mapped[str | None] = mapped_column(String(128))
    source_row_scope_migration_failure_details: Mapped[dict | None] = mapped_column(JSONB)
    calculation_status: Mapped[str | None] = mapped_column(String(32))
    calculation_block_reason: Mapped[str | None] = mapped_column(String(128))
    import_status: Mapped[str | None] = mapped_column(String(32))
    supersedes_batch_id: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    is_active: Mapped[bool | None] = mapped_column(Boolean)
    taxonomy_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    variant_schema_version: Mapped[str | None] = mapped_column(String(128))
    taxonomy_resolution_mode: Mapped[str | None] = mapped_column(String(64))
    taxonomy_locked: Mapped[bool | None] = mapped_column(Boolean)
    work_rate_catalog_version: Mapped[str | None] = mapped_column(String(64))
    work_rate_catalog_hash: Mapped[str | None] = mapped_column(String(128))
    projection_generation_status: Mapped[str | None] = mapped_column(String(64))
    projection_failure_code: Mapped[str | None] = mapped_column(String(128))
    projection_failure_details: Mapped[dict | None] = mapped_column(JSONB)
    revalidated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    revalidated_by_user_id: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        server_default=sa_text("NOW()"),
    )

    project: Mapped["Project"] = relationship(back_populates="estimate_batches")
    estimates: Mapped[list["Estimate"]] = relationship(back_populates="estimate_batch")
    gantt_tasks: Mapped[list["GanttTask"]] = relationship(back_populates="estimate_batch")
