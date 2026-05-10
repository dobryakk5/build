"""
Модели справочника нормализованных видов работ (NW).

Иерархия:
  NwWorkType  (WT-01..WT-11)         — верхний уровень
    └─ NwItem (NW-001..NW-087)       — нормализованный вид работ

Атрибуты NwItem ссылаются на справочники массивами кодов:
  NwObjectType         (OT-01..OT-12)
  NwBuildingTechnology (BT-01..BT-06)
  NwLocationScope      (LS-01..LS-11)
  NwStage              (ST-01..ST-12)
  NwRepairClass        (none/current/capital/reconstruction)

Все таблицы — в схеме `fer.`
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Numeric,
    PrimaryKeyConstraint, SmallInteger, String, Text, TIMESTAMP,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

TIMESTAMPTZ = TIMESTAMP(timezone=True)

from .base import Base


# ─────────────────────────── reference tables ───────────────────────────

class NwWorkType(Base):
    __tablename__ = "nw_work_type"
    __table_args__ = {"schema": "fer"}

    code:        Mapped[str]       = mapped_column(String(10), primary_key=True)
    name:        Mapped[str]       = mapped_column(Text, nullable=False)
    description: Mapped[str|None]  = mapped_column(Text)
    sort_order:  Mapped[int]       = mapped_column(SmallInteger, nullable=False, server_default="0")

    items: Mapped[list["NwItem"]] = relationship(back_populates="work_type")


class NwObjectType(Base):
    __tablename__ = "nw_object_type"
    __table_args__ = {"schema": "fer"}

    code:       Mapped[str] = mapped_column(String(10), primary_key=True)
    name:       Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class NwBuildingTechnology(Base):
    __tablename__ = "nw_building_technology"
    __table_args__ = {"schema": "fer"}

    code:       Mapped[str] = mapped_column(String(10), primary_key=True)
    name:       Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class NwLocationScope(Base):
    __tablename__ = "nw_location_scope"
    __table_args__ = {"schema": "fer"}

    code:       Mapped[str] = mapped_column(String(10), primary_key=True)
    name:       Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class NwStage(Base):
    __tablename__ = "nw_stage"
    __table_args__ = {"schema": "fer"}

    code:       Mapped[str] = mapped_column(String(10), primary_key=True)
    name:       Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class NwRepairClass(Base):
    __tablename__ = "nw_repair_class"
    __table_args__ = {"schema": "fer"}

    code:        Mapped[str] = mapped_column(String(20), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order:  Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


# ─────────────────────────── main: nw_item ───────────────────────────

class NwItem(Base):
    """
    Нормализованный вид работ. Иерархия двухуровневая: work_type → item.
    Атрибуты (object_type / building_technology / ...) хранятся как массивы кодов
    — FK constraints на массивы PostgreSQL не поддерживает, валидация на уровне приложения.
    """
    __tablename__ = "nw_item"
    __table_args__ = (
        UniqueConstraint("unique_label", name="uq_nw_item_unique_label"),
        Index("ix_nw_item_work_type_code", "work_type_code"),
        {"schema": "fer"},
    )

    code:         Mapped[str]        = mapped_column(String(10), primary_key=True)
    unique_label: Mapped[str]        = mapped_column(Text, nullable=False)
    work_type_code: Mapped[str]      = mapped_column(
        String(10),
        ForeignKey("fer.nw_work_type.code", ondelete="RESTRICT"),
        nullable=False,
    )
    subtype:                   Mapped[str|None]  = mapped_column(Text)
    object_type_codes:         Mapped[list[str]] = mapped_column(ARRAY(String(10)), nullable=False, server_default=text("'{}'::text[]"))
    building_technology_codes: Mapped[list[str]] = mapped_column(ARRAY(String(10)), nullable=False, server_default=text("'{}'::text[]"))
    location_scope_codes:      Mapped[list[str]] = mapped_column(ARRAY(String(10)), nullable=False, server_default=text("'{}'::text[]"))
    stage_codes:               Mapped[list[str]] = mapped_column(ARRAY(String(10)), nullable=False, server_default=text("'{}'::text[]"))
    repair_class_codes:        Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, server_default=text("'{}'::text[]"))
    is_capital_repair:         Mapped[bool|None] = mapped_column(Boolean)
    requires_permit_review:    Mapped[bool]      = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notes:                     Mapped[str|None]  = mapped_column(Text)
    sort_order:                Mapped[int]       = mapped_column(SmallInteger, nullable=False, server_default="0")

    work_type: Mapped["NwWorkType"] = relationship(back_populates="items")


# ─────────────────────────── NW ↔ FER mapping ───────────────────────────

class NwFerMapping(Base):
    """
    Long-table связь ФЕР раздела (collection_num × section_num) с NW.
    Один раздел ↔ N NW. Используется при классификации сметных строк.
    """
    __tablename__ = "nw_fer_mapping"
    __table_args__ = (
        UniqueConstraint(
            "fer_collection_num", "fer_section_num", "nw_item_code",
            name="uq_nw_fer_mapping_section_nw",
        ),
        Index("ix_nw_fer_mapping_nw_code", "nw_item_code"),
        Index("ix_nw_fer_mapping_section", "fer_collection_num", "fer_section_num"),
        {"schema": "fer"},
    )

    id:                 Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fer_collection_num: Mapped[int]      = mapped_column(SmallInteger, nullable=False)
    fer_section_num:    Mapped[int]      = mapped_column(SmallInteger, nullable=False)
    nw_item_code:       Mapped[str]      = mapped_column(
        String(10),
        ForeignKey("fer.nw_item.code", ondelete="CASCADE"),
        nullable=False,
    )
    mapping_type:       Mapped[str]      = mapped_column(String(32), nullable=False)
    confidence:         Mapped[str]      = mapped_column(String(16), nullable=False)
    is_primary:         Mapped[bool]     = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notes:              Mapped[str|None] = mapped_column(Text)


# ─────────────────────────── NW ↔ ФЕР таблица (детальный уровень) ───────────────────────────

class NwFerTableMapping(Base):
    """
    Маппинг конкретной ФЕР-таблицы (fer.fer_tables) на NW.
    Уровень глубже, чем NwFerMapping (там был раздел).

    nw_item_code = NULL и mapping_type='needs_llm_review' — таблица помечена для
    LLM-разбора (классификатор не дал уверенного результата).
    """
    __tablename__ = "nw_fer_table_mapping"
    __table_args__ = (
        UniqueConstraint(
            "fer_table_id", "nw_item_code",
            name="uq_nw_fer_table_mapping_table_nw",
        ),
        Index("ix_nw_fer_table_mapping_nw", "nw_item_code"),
        Index("ix_nw_fer_table_mapping_table", "fer_table_id"),
        {"schema": "fer"},
    )

    id:           Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fer_table_id: Mapped[int]      = mapped_column(BigInteger, nullable=False)
    nw_item_code: Mapped[str|None] = mapped_column(
        String(10),
        ForeignKey("fer.nw_item.code", ondelete="CASCADE"),
        nullable=True,
    )
    mapping_type: Mapped[str]      = mapped_column(String(32), nullable=False)
    confidence:   Mapped[str]      = mapped_column(String(16), nullable=False)
    is_primary:   Mapped[bool]     = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source:       Mapped[str]      = mapped_column(String(24), nullable=False)
    notes:        Mapped[str|None] = mapped_column(Text)


# ─────────────────────────── Project Work Plan (КТП проекта) ───────────────────────────

class ProjectWorkPlan(Base):
    """
    Карточка плана работ — детальная запись «что/сколько/за сколько/когда».

    Создаётся из загруженной сметы (auto), уточняется прорабом, потом обогащается
    точной ФЕР расценкой и расчётом длительности.

    Декомпозиция: для агрегатных NW (NW-021 «дом под ключ») создаётся родитель
    + пачка дочерних (parent_id ссылается).
    """
    __tablename__ = "project_work_plan"
    __table_args__ = (
        CheckConstraint(
            "status IN ('auto_proposed','confirmed','removed','custom_added',"
            "'fer_mapped','scheduled','needs_volume','needs_review')",
            name="ck_pwp_status",
        ),
        Index("ix_pwp_batch",     "estimate_batch_id"),
        Index("ix_pwp_nw",        "nw_item_code"),
        Index("ix_pwp_parent",    "parent_id"),
        Index("ix_pwp_fer_table", "fer_table_id"),
        Index("ix_pwp_status",    "status"),
        {"schema": "fer"},
    )

    id:                Mapped[int]            = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    estimate_batch_id: Mapped[str]            = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("estimate_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id:         Mapped[int|None]       = mapped_column(
        BigInteger,
        ForeignKey("fer.project_work_plan.id", ondelete="CASCADE"),
        nullable=True,
    )

    # ЧТО
    nw_item_code:             Mapped[str]      = mapped_column(
        String(10),
        ForeignKey("fer.nw_item.code", ondelete="RESTRICT"),
        nullable=False,
    )
    object_type_code:         Mapped[str|None] = mapped_column(String(10))
    building_technology_code: Mapped[str|None] = mapped_column(String(10))
    location_scope_code:      Mapped[str|None] = mapped_column(String(10))
    stage_code:               Mapped[str|None] = mapped_column(String(10))
    is_capital_repair:        Mapped[bool|None] = mapped_column(Boolean)

    # СКОЛЬКО
    unit:     Mapped[str|None]   = mapped_column(String(20))
    quantity: Mapped[float|None] = mapped_column(Numeric(12, 3))

    # ИСХОДНОЕ из сметы (для отображения «как было написано»)
    source_label:   Mapped[str|None] = mapped_column(Text)
    source_section: Mapped[str|None] = mapped_column(Text)

    # ЗА СКОЛЬКО (ФЕР)
    fer_table_id:         Mapped[int|None]      = mapped_column(BigInteger)
    fer_row_id:           Mapped[int|None]      = mapped_column(BigInteger)
    fer_match_score:      Mapped[float|None]    = mapped_column(Numeric(5, 4))
    fer_match_source:     Mapped[str|None]      = mapped_column(String(16))
    fer_candidates:       Mapped[list|None]     = mapped_column(JSONB)
    fer_matched_at:       Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    human_hours_per_unit: Mapped[float|None]    = mapped_column(Numeric(12, 3))

    # КОГДА
    workers_count: Mapped[int|None]   = mapped_column(SmallInteger)
    duration_days: Mapped[float|None] = mapped_column(Numeric(8, 2))

    # СТАТУС / МЕТА
    status:       Mapped[str]            = mapped_column(String(20), nullable=False, server_default="auto_proposed")
    notes:        Mapped[str|None]       = mapped_column(Text)
    created_by:   Mapped[str|None]       = mapped_column(PGUUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    created_at:   Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"), nullable=False)
    updated_at:   Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"), nullable=False)
    confirmed_at: Mapped[datetime|None]  = mapped_column(TIMESTAMPTZ)

    nw_item:  Mapped["NwItem"]                       = relationship()
    children: Mapped[list["ProjectWorkPlan"]]        = relationship(
        "ProjectWorkPlan",
        backref="parent",
        remote_side="ProjectWorkPlan.id",
    )
    estimate_links: Mapped[list["ProjectWorkPlanEstimateLink"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
    )


class ProjectWorkPlanEstimateLink(Base):
    """Связь карточка плана ↔ строка сметы (откуда взят объём)."""
    __tablename__ = "project_work_plan_estimate_link"
    __table_args__ = (
        PrimaryKeyConstraint("plan_id", "estimate_id"),
        Index("ix_pwp_link_estimate", "estimate_id"),
        {"schema": "fer"},
    )

    plan_id:     Mapped[int]   = mapped_column(
        BigInteger,
        ForeignKey("fer.project_work_plan.id", ondelete="CASCADE"),
        nullable=False,
    )
    estimate_id: Mapped[str]   = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
    )
    share:       Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, server_default=text("1.0"))

    plan: Mapped["ProjectWorkPlan"] = relationship(back_populates="estimate_links")
