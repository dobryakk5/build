"""Справочник видов работ (макротип + подтип) и граф предшествования.

Источники-эталоны лежат в ``backend/app/data/work_subtypes.csv`` и
``work_precedence.csv`` и засеиваются в эти таблицы миграцией. Подтип
присваивается work-строкам сметы по keywords (см. work_taxonomy_service), а
граф предшествования соединяет задачи Ганта по subtype_code.
"""
from sqlalchemy import Integer, Numeric, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
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

    # Дефолты производительности (заполняются экспертом в справочнике; могут быть NULL).
    output_per_day: Mapped[float | None] = mapped_column(Numeric(12, 3))   # ед/смену
    crew_size:      Mapped[int | None]   = mapped_column(SmallInteger)     # типовая бригада
    lag_after_days: Mapped[int]          = mapped_column(Integer, nullable=False, server_default=text("0"))
    default_unit:   Mapped[str | None]   = mapped_column(Text)


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
