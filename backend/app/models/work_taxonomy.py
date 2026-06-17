"""Справочник видов работ (макротип + подтип) и граф предшествования.

Источники-эталоны лежат в ``backend/app/data/work_subtypes.csv`` и
``work_precedence.csv`` и засеиваются в эти таблицы миграцией. Подтип
присваивается work-строкам сметы по keywords (см. work_taxonomy_service), а
граф предшествования соединяет задачи Ганта по subtype_code.
"""
from sqlalchemy import Boolean, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WorkSubtype(Base):
    __tablename__ = "work_subtypes"

    id:         Mapped[int]       = mapped_column(Integer, primary_key=True)
    macro_id:   Mapped[int]       = mapped_column(Integer, nullable=False)
    macro_name: Mapped[str]       = mapped_column(Text, nullable=False)
    code:       Mapped[str]       = mapped_column(Text, nullable=False, unique=True)  # напр. "2.3"
    name:       Mapped[str]       = mapped_column(Text, nullable=False)
    keywords:   Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    section_code: Mapped[str | None] = mapped_column(Text)
    section_name: Mapped[str | None] = mapped_column(Text)
    section_scope: Mapped[str | None] = mapped_column(Text)
    dictionary_source: Mapped[str | None] = mapped_column(String(64))
    dictionary_name: Mapped[str | None] = mapped_column(Text)
    dictionary_schema_version: Mapped[str | None] = mapped_column(String(32))
    dictionary_source_version: Mapped[str | None] = mapped_column(String(64))
    legacy_code: Mapped[str | None] = mapped_column(Text)
    display_code: Mapped[str | None] = mapped_column(Text)
    legacy_csv_codes: Mapped[list[str] | None] = mapped_column(JSONB)
    terms_json: Mapped[dict | None] = mapped_column(JSONB)
    scoring_json: Mapped[dict | None] = mapped_column(JSONB)
    aliases_json: Mapped[list[dict] | None] = mapped_column(JSONB)

    # Дефолты производительности (заполняются экспертом в справочнике; могут быть NULL).
    output_per_day: Mapped[float | None] = mapped_column(Numeric(12, 3))   # ед/смену
    crew_size:      Mapped[int | None]   = mapped_column(SmallInteger)     # типовая бригада
    lag_after_days: Mapped[int]          = mapped_column(Integer, nullable=False, server_default=text("0"))
    default_unit:   Mapped[str | None]   = mapped_column(Text)


class WorkSubtypeAlias(Base):
    __tablename__ = "work_subtype_aliases"
    __table_args__ = (
        UniqueConstraint(
            "alias_source",
            "alias_code",
            "target_level",
            "target_code",
            name="uq_work_subtype_alias_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias_code: Mapped[str] = mapped_column(Text, nullable=False)
    alias_source: Mapped[str] = mapped_column(String(64), nullable=False)
    target_level: Mapped[str] = mapped_column(String(16), nullable=False)
    target_code: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_code: Mapped[str | None] = mapped_column(Text)
    mapping_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(16))
    transfer_defaults: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)


class WorkPrecedence(Base):
    __tablename__ = "work_precedence"
    __table_args__ = (
        UniqueConstraint("predecessor_code", "successor_code", name="uq_work_precedence_pair"),
    )

    id:               Mapped[int]      = mapped_column(Integer, primary_key=True)
    predecessor_code: Mapped[str]      = mapped_column(Text, nullable=False)
    successor_code:   Mapped[str]      = mapped_column(Text, nullable=False)
    lag_days:         Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    note:             Mapped[str|None] = mapped_column(Text, nullable=True)
