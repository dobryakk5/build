from __future__ import annotations

import uuid

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class KtpEstimateSession(Base, TimestampMixin):
    """Один прогон AI-flow «КТП по смете» на батч сметы."""

    __tablename__ = "ktp_estimate_sessions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "estimate_batch_id",
            name="uq_ktp_estimate_sessions_project_batch",
        ),
    )

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False), primary_key=True, default=_uuid
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    estimate_batch_id: Mapped[str] = mapped_column(
        ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="stage1_pending"
    )
    stage1_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    stage1_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    gpr_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    stage1_raw_json: Mapped[dict | None] = mapped_column(JSONB)
    llm_model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)

    groups: Mapped[list["KtpWbsGroup"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="KtpWbsGroup.sort_order",
    )


class KtpWbsGroup(Base, TimestampMixin):
    """Группа технологической последовательности внутри сеанса."""

    __tablename__ = "ktp_wbs_groups"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False), primary_key=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("ktp_estimate_sessions.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[float] = mapped_column(
        Numeric(20, 10), nullable=False, server_default="1000"
    )
    wt_code: Mapped[str | None] = mapped_column(String(10))
    wt_name: Mapped[str | None] = mapped_column(Text)
    work_section_code: Mapped[str | None] = mapped_column(Text)
    work_section_name: Mapped[str | None] = mapped_column(Text)
    work_type_confidence: Mapped[str | None] = mapped_column(String(16))
    work_type_source: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="draft"
    )
    stage_instance_id: Mapped[str | None] = mapped_column(String(255))
    template_stage_number: Mapped[str | None] = mapped_column(String(64))
    stage_number: Mapped[str | None] = mapped_column(String(64))
    floor_number: Mapped[int | None] = mapped_column(Integer)
    floor_kind: Mapped[str | None] = mapped_column(String(32))
    floor_label: Mapped[str | None] = mapped_column(String(128))
    floor_component: Mapped[str | None] = mapped_column(String(64))
    component_role: Mapped[str | None] = mapped_column(String(128))
    # Этап 2 — карточка КТП
    card_title: Mapped[str | None] = mapped_column(Text)
    card_goal: Mapped[str | None] = mapped_column(Text)
    card_steps_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    card_recommendations_json: Mapped[list[str] | None] = mapped_column(JSONB)
    card_questions_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    card_answers_json: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    card_error_message: Mapped[str | None] = mapped_column(Text)
    # Этап 3 — ГПР
    start_date: Mapped[date | None] = mapped_column(Date)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    gantt_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("gantt_tasks.id", ondelete="SET NULL")
    )

    session: Mapped["KtpEstimateSession"] = relationship(back_populates="groups")
    items: Mapped[list["KtpWbsItem"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="KtpWbsItem.sort_order",
    )


class KtpWbsItem(Base, TimestampMixin):
    """Работа (лист WBS)."""

    __tablename__ = "ktp_wbs_items"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False), primary_key=True, default=_uuid
    )
    group_id: Mapped[str] = mapped_column(
        ForeignKey("ktp_wbs_groups.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("ktp_estimate_sessions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[float] = mapped_column(
        Numeric(20, 10), nullable=False, server_default="1000"
    )
    # from_estimate | ai_added | manual
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="from_estimate"
    )
    estimate_id: Mapped[str | None] = mapped_column(
        ForeignKey("estimates.id", ondelete="SET NULL")
    )
    unit: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 3))
    # estimate | ai_estimated | user
    quantity_source: Mapped[str | None] = mapped_column(String(16))
    # pending | accepted | rejected
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="accepted"
    )
    ai_reason: Mapped[str | None] = mapped_column(Text)
    # Этап 3 — нормы и длительность
    norm_source: Mapped[str | None] = mapped_column(String(8))  # enir | fer | ai
    norm_ref: Mapped[str | None] = mapped_column(String(64))
    # norm_time | vyrabotka | fallback | manual
    norm_kind: Mapped[str | None] = mapped_column(String(12))
    norm_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    norm_unit: Mapped[str | None] = mapped_column(String(32))
    brigade_size: Mapped[int | None] = mapped_column(SmallInteger)
    labor_hours: Mapped[float | None] = mapped_column(Numeric(12, 2))
    duration_days: Mapped[int | None] = mapped_column(Integer)
    gantt_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("gantt_tasks.id", ondelete="SET NULL")
    )

    # Диспозиция строки сметы: work | excluded (субитоги/ИТОГО/несторительные).
    disposition: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="work"
    )
    disposition_reason: Mapped[str | None] = mapped_column(Text)
    # regex | llm | manual
    disposition_source: Mapped[str | None] = mapped_column(String(16))

    # NW-скоуп (диагностический — только для сужения области поиска ФЕР).
    nw_item_code: Mapped[str | None] = mapped_column(String(10))
    # keyword | broad | manual
    nw_match_source: Mapped[str | None] = mapped_column(String(16))
    nw_match_reason: Mapped[str | None] = mapped_column(Text)
    nw_match_candidates: Mapped[list | None] = mapped_column(JSONB)
    nw_manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    work_section_code: Mapped[str | None] = mapped_column(Text)
    work_section_name: Mapped[str | None] = mapped_column(Text)
    work_subtype_code: Mapped[str | None] = mapped_column(Text)
    work_subtype_name: Mapped[str | None] = mapped_column(Text)
    work_type_confidence: Mapped[str | None] = mapped_column(String(16))
    work_type_needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    work_type_candidates: Mapped[list | None] = mapped_column(JSONB)
    work_type_source: Mapped[str | None] = mapped_column(String(32))
    operator_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    gpr_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # Сопоставление с конкретной строкой ФЕР (источник трудоёмкости h_hour).
    fer_table_id: Mapped[int | None] = mapped_column(BigInteger)
    fer_row_id: Mapped[int | None] = mapped_column(BigInteger)
    # auto | review | manual
    fer_match_source: Mapped[str | None] = mapped_column(String(16))
    fer_match_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    fer_match_candidates: Mapped[list | None] = mapped_column(JSONB)
    fer_manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Трудоёмкость подобранной строки ФЕР (чел-ч на единицу ФЕР).
    fer_h_hour: Mapped[float | None] = mapped_column(Numeric(12, 4))
    # Единица измерения ФЕР (эвристически извлечённая) и множитель (напр. «на 100 м2»).
    fer_unit: Mapped[str | None] = mapped_column(String(32))
    fer_unit_multiplier: Mapped[float | None] = mapped_column(Numeric(12, 4))
    source_row_key: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    projection_id: Mapped[str | None] = mapped_column(String(96))
    stage_instance_id: Mapped[str | None] = mapped_column(String(255))
    template_stage_number: Mapped[str | None] = mapped_column(String(64))
    stage_number: Mapped[str | None] = mapped_column(String(64))
    floor_number: Mapped[int | None] = mapped_column(Integer)
    floor_kind: Mapped[str | None] = mapped_column(String(32))
    floor_label: Mapped[str | None] = mapped_column(String(128))
    floor_component: Mapped[str | None] = mapped_column(String(64))
    component_role: Mapped[str | None] = mapped_column(String(128))
    operation_code: Mapped[str | None] = mapped_column(String(128))
    operation_package_code: Mapped[str | None] = mapped_column(String(128))
    semantic_stage_option_id: Mapped[str | None] = mapped_column(String(128))
    stage_option_source: Mapped[str | None] = mapped_column(String(64))
    work_scope_key: Mapped[str | None] = mapped_column(String(255))
    applicability_hash: Mapped[str | None] = mapped_column(String(64))
    applicability_hash_version: Mapped[int | None] = mapped_column(SmallInteger)
    applicability_schema_version: Mapped[str | None] = mapped_column(String(64))
    duration_block_reason: Mapped[str | None] = mapped_column(String(128))

    group: Mapped["KtpWbsGroup"] = relationship(back_populates="items")


class KtpWbsGroupDependency(Base):
    """FS-зависимость между группами WBS."""

    __tablename__ = "ktp_wbs_group_dependencies"

    group_id: Mapped[str] = mapped_column(
        ForeignKey("ktp_wbs_groups.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_group_id: Mapped[str] = mapped_column(
        ForeignKey("ktp_wbs_groups.id", ondelete="CASCADE"), primary_key=True
    )


class KtpSessionSubtype(Base, TimestampMixin):
    """Производительность по подтипу работ в рамках сеанса (этап 4).

    Одна строка = (подтип работ, единица измерения) использованный в смете. Оператор
    задаёт производительность бригады за смену, размер бригады и техпаузу после.
    Дефолты подтягиваются из справочника ``work_subtypes`` и помечаются ``*_source``;
    ручные правки (``manual``) не перезатираются при перестроении из сметы.
    """

    __tablename__ = "ktp_session_subtypes"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "subtype_code", "unit",
            name="uq_ktp_session_subtypes_session_code_unit",
        ),
    )

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False), primary_key=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("ktp_estimate_sessions.id", ondelete="CASCADE"), nullable=False
    )
    subtype_code: Mapped[str] = mapped_column(Text, nullable=False)
    subtype_name: Mapped[str] = mapped_column(Text, nullable=False)
    work_subtype_code: Mapped[str | None] = mapped_column(Text)
    work_subtype_name: Mapped[str | None] = mapped_column(Text)
    item_id: Mapped[str | None] = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("ktp_wbs_items.id", ondelete="CASCADE"),
    )
    session_subtype_key: Mapped[str | None] = mapped_column(Text)
    macro_name: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(50))
    volume: Mapped[float | None] = mapped_column(Numeric(12, 3))
    output_per_day: Mapped[float | None] = mapped_column(Numeric(12, 3))
    crew_size: Mapped[int | None] = mapped_column(SmallInteger)
    lag_after_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    # default | manual — пометки источника, чтобы rebuild не перезатирал ручные правки
    output_source: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="default"
    )
    crew_source: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="default"
    )
    lag_source: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="default"
    )
    rate_unit_conversion: Mapped[dict | None] = mapped_column(JSONB)
