"""
Модели справочника ЕНИР.

Иерархия:
  EnirCollection          — сборник  (Е1, Е2, Е3 …)
    └─ EnirParagraph      — параграф (Е3-1, Е3-2 …)
         ├─ EnirWorkComposition  — условие / группа состава работ
         │    └─ EnirWorkOperation — строка состава работ
         ├─ EnirCrewMember       — состав звена (профессия, разряд, кол-во)
         ├─ EnirNormTable        — таблица норм в JSONB
         └─ EnirNote             — примечание к параграфу
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Date, ForeignKey, Integer, Numeric, SmallInteger,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base

TIMESTAMPTZ = TIMESTAMP(timezone=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Сборник ЕНИР
# ─────────────────────────────────────────────────────────────────────────────
class EnirCollection(Base):
    """
    Сборник ЕНИР: Е1 «Земляные работы», Е3 «Каменные работы» и т.д.
    code должен быть уникальным: 'Е1', 'Е2', 'Е3', ...
    """
    __tablename__ = "enir_collections"

    id:          Mapped[int]       = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code:        Mapped[str]       = mapped_column(String(20),  nullable=False, unique=True)
    title:       Mapped[str]       = mapped_column(Text,        nullable=False)
    schema_version: Mapped[int]    = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    source_file: Mapped[str]       = mapped_column(String(255), nullable=False, default="", server_default=text("''"))
    description: Mapped[str|None]  = mapped_column(Text)
    issuing_bodies: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    approval_date: Mapped[date | None] = mapped_column(Date)
    approval_number: Mapped[str]   = mapped_column(String(100), nullable=False, default="", server_default=text("''"))
    developer: Mapped[str]         = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    coordination: Mapped[str]      = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    amendments: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Порядок отображения в UI (можно задать вручную: 1, 2, 3 …)
    sort_order:  Mapped[int]       = mapped_column(Integer, default=0, nullable=False)
    created_at:  Mapped[datetime]  = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))

    paragraphs: Mapped[list["EnirParagraph"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="EnirParagraph.sort_order",
    )

    def __repr__(self) -> str:
        return f"<EnirCollection {self.code} — {self.title}>"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Параграф
# ─────────────────────────────────────────────────────────────────────────────
class EnirParagraph(Base):
    """
    Параграф внутри сборника.
    code уникален внутри сборника: 'Е3-1', 'Е3-2' …
    unit — измеритель нормы: 'м3 кладки', '100 м2' и т.д.
    """
    __tablename__ = "enir_paragraphs"
    __table_args__ = (
        UniqueConstraint("collection_id", "code", name="uq_enir_paragraph_code"),
    )

    id:            Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id: Mapped[int]      = mapped_column(
        BigInteger, ForeignKey("enir_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code:          Mapped[str]      = mapped_column(String(30),  nullable=False)
    title:         Mapped[str]      = mapped_column(Text,        nullable=False)
    unit:          Mapped[str|None] = mapped_column(String(100))
    sort_order:    Mapped[int]      = mapped_column(Integer, default=0, nullable=False)

    collection:        Mapped["EnirCollection"]           = relationship(back_populates="paragraphs")
    work_compositions: Mapped[list["EnirWorkComposition"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirWorkComposition.sort_order"
    )
    crew:              Mapped[list["EnirCrewMember"]]      = relationship(
        back_populates="paragraph", cascade="all, delete-orphan"
    )
    norm_tables:       Mapped[list["EnirNormTable"]]       = relationship(
        back_populates="paragraph", cascade="all, delete-orphan",
        order_by="EnirNormTable.table_order"
    )
    notes:             Mapped[list["EnirNote"]]            = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirNote.num"
    )

    def __repr__(self) -> str:
        return f"<EnirParagraph {self.code}>"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Состав работ
# ─────────────────────────────────────────────────────────────────────────────
class EnirWorkComposition(Base):
    """
    Условие / блок состава работ внутри параграфа.
    condition — текст условия применения (может быть пустым, если один блок).
    """
    __tablename__ = "enir_work_compositions"

    id:           Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int]      = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    condition:    Mapped[str|None] = mapped_column(Text)
    sort_order:   Mapped[int]      = mapped_column(Integer, default=0, nullable=False)

    paragraph:  Mapped["EnirParagraph"]           = relationship(back_populates="work_compositions")
    operations: Mapped[list["EnirWorkOperation"]] = relationship(
        back_populates="composition", cascade="all, delete-orphan", order_by="EnirWorkOperation.sort_order"
    )


class EnirWorkOperation(Base):
    """Одна строка операции внутри блока состава работ."""
    __tablename__ = "enir_work_operations"

    id:             Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    composition_id: Mapped[int]  = mapped_column(
        BigInteger, ForeignKey("enir_work_compositions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text:           Mapped[str]  = mapped_column(Text, nullable=False)
    sort_order:     Mapped[int]  = mapped_column(Integer, default=0, nullable=False)

    composition: Mapped["EnirWorkComposition"] = relationship(back_populates="operations")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Состав звена
# ─────────────────────────────────────────────────────────────────────────────
class EnirCrewMember(Base):
    """Профессия / разряд / количество рабочих в звене."""
    __tablename__ = "enir_crew_members"

    id:           Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int]      = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profession:   Mapped[str]      = mapped_column(String(200), nullable=False)
    # grade — разряд; может быть дробным (3.5) или null (ИТР)
    grade:        Mapped[float|None] = mapped_column(Numeric(4, 1))
    count:        Mapped[int]      = mapped_column(SmallInteger, nullable=False, default=1)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="crew")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Таблицы норм (JSONB)
# ─────────────────────────────────────────────────────────────────────────────
class EnirNormTable(Base):
    """
    Одна логическая таблица норм внутри параграфа.
    Столбцы и строки хранятся в JSONB без уплощения структуры исходника.
    """
    __tablename__ = "enir_norm_tables"

    id:           Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id:     Mapped[str]        = mapped_column(String(120), nullable=False, unique=True)
    paragraph_id: Mapped[int]        = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_order:  Mapped[int]        = mapped_column(Integer, default=0, nullable=False)
    title:        Mapped[str]        = mapped_column(Text, nullable=False, default="")
    row_count:    Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    columns:      Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    rows:         Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="norm_tables")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Примечания
# ─────────────────────────────────────────────────────────────────────────────
class EnirNote(Base):
    """Примечание к параграфу. Может содержать коэффициент поправки."""
    __tablename__ = "enir_notes"

    id:           Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int]        = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    num:          Mapped[int]        = mapped_column(SmallInteger, nullable=False)
    text:         Mapped[str]        = mapped_column(Text, nullable=False)
    # Коэффициент поправки (1.15, 1.1 …), NULL — просто текстовое примечание
    coefficient:  Mapped[float|None] = mapped_column(Numeric(6, 4))
    # Код таблицы коэффициентов (ПР-1, ПР-2 …)
    pr_code:      Mapped[str|None]   = mapped_column(String(20))

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="notes")
