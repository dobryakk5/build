"""
Модели справочника ЕНИР.

Иерархия:
  EnirCollection          — сборник  (Е1, Е2, Е3 …)
    └─ EnirParagraph      — параграф (Е3-1, Е3-2 …)
         ├─ EnirWorkComposition  — условие / группа состава работ
         │    └─ EnirWorkOperation — строка состава работ
         ├─ EnirCrewMember       — состав звена (профессия, разряд, кол-во)
         ├─ EnirNorm             — строка таблицы норм (Н.вр + Расц.)
         └─ EnirNote             — примечание к параграфу
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, SmallInteger,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    description: Mapped[str|None]  = mapped_column(Text)
    issue:       Mapped[str|None]  = mapped_column(String(100))
    issue_title: Mapped[str|None]  = mapped_column(Text)
    source_file: Mapped[str|None]  = mapped_column(Text)
    source_format: Mapped[str|None] = mapped_column(String(50))
    # Порядок отображения в UI (можно задать вручную: 1, 2, 3 …)
    sort_order:  Mapped[int]       = mapped_column(Integer, default=0, nullable=False)
    created_at:  Mapped[datetime]  = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))

    paragraphs: Mapped[list["EnirParagraph"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="EnirParagraph.sort_order",
    )
    sections: Mapped[list["EnirSection"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="EnirSection.sort_order",
    )
    technical_coefficients: Mapped[list["EnirTechnicalCoefficient"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="EnirTechnicalCoefficient.sort_order",
    )

    def __repr__(self) -> str:
        return f"<EnirCollection {self.code} — {self.title}>"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Структура сборника: разделы и главы
# ─────────────────────────────────────────────────────────────────────────────
class EnirSection(Base):
    """Раздел сборника ENIR, например 'Раздел I. КАМЕННЫЕ КОНСТРУКЦИИ ЗДАНИЙ'."""
    __tablename__ = "enir_sections"
    __table_args__ = (
        UniqueConstraint("collection_id", "source_section_id", name="uq_enir_section_source_id"),
    )

    id:                Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id:     Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_section_id: Mapped[str] = mapped_column(String(60), nullable=False)
    title:             Mapped[str] = mapped_column(Text, nullable=False)
    sort_order:        Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_tech:          Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    collection: Mapped["EnirCollection"] = relationship(back_populates="sections")
    chapters: Mapped[list["EnirChapter"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="EnirChapter.sort_order"
    )
    paragraphs: Mapped[list["EnirParagraph"]] = relationship(back_populates="section")
    technical_coefficients: Mapped[list["EnirTechnicalCoefficient"]] = relationship(
        back_populates="section"
    )


class EnirChapter(Base):
    """Глава внутри раздела ENIR."""
    __tablename__ = "enir_chapters"
    __table_args__ = (
        UniqueConstraint("collection_id", "source_chapter_id", name="uq_enir_chapter_source_id"),
    )

    id:                Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id:     Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id:        Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_chapter_id: Mapped[str] = mapped_column(String(60), nullable=False)
    title:             Mapped[str] = mapped_column(Text, nullable=False)
    sort_order:        Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_tech:          Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    collection: Mapped["EnirCollection"] = relationship()
    section: Mapped["EnirSection"] = relationship(back_populates="chapters")
    paragraphs: Mapped[list["EnirParagraph"]] = relationship(back_populates="chapter")
    technical_coefficients: Mapped[list["EnirTechnicalCoefficient"]] = relationship(
        back_populates="chapter"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Параграф
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
    section_id: Mapped[int|None] = mapped_column(
        BigInteger, ForeignKey("enir_sections.id", ondelete="SET NULL"), index=True
    )
    chapter_id: Mapped[int|None] = mapped_column(
        BigInteger, ForeignKey("enir_chapters.id", ondelete="SET NULL"), index=True
    )
    source_paragraph_id: Mapped[str|None] = mapped_column(String(60))
    code:          Mapped[str]      = mapped_column(String(30),  nullable=False)
    title:         Mapped[str]      = mapped_column(Text,        nullable=False)
    unit:          Mapped[str|None] = mapped_column(String(100))
    html_anchor:   Mapped[str|None] = mapped_column(String(100))
    sort_order:    Mapped[int]      = mapped_column(Integer, default=0, nullable=False)

    collection:        Mapped["EnirCollection"]           = relationship(back_populates="paragraphs")
    section:           Mapped["EnirSection | None"]       = relationship(back_populates="paragraphs")
    chapter:           Mapped["EnirChapter | None"]       = relationship(back_populates="paragraphs")
    work_compositions: Mapped[list["EnirWorkComposition"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirWorkComposition.sort_order"
    )
    crew:              Mapped[list["EnirCrewMember"]]      = relationship(
        back_populates="paragraph", cascade="all, delete-orphan"
    )
    norms:             Mapped[list["EnirNorm"]]            = relationship(
        back_populates="paragraph", cascade="all, delete-orphan",
        order_by="(EnirNorm.row_num, EnirNorm.column_label)"
    )
    notes:             Mapped[list["EnirNote"]]            = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirNote.num"
    )
    technical_characteristics: Mapped[list["EnirParagraphTechnicalCharacteristic"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan",
        order_by="EnirParagraphTechnicalCharacteristic.sort_order"
    )
    application_notes: Mapped[list["EnirParagraphApplicationNote"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan",
        order_by="EnirParagraphApplicationNote.sort_order"
    )
    paragraph_refs: Mapped[list["EnirParagraphRef"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirParagraphRef.sort_order"
    )
    source_work_items: Mapped[list["EnirSourceWorkItem"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirSourceWorkItem.sort_order"
    )
    source_crew_items: Mapped[list["EnirSourceCrewItem"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirSourceCrewItem.sort_order"
    )
    source_notes: Mapped[list["EnirSourceNote"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirSourceNote.sort_order"
    )
    norm_tables: Mapped[list["EnirNormTable"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan", order_by="EnirNormTable.sort_order"
    )
    technical_coefficients: Mapped[list["EnirTechnicalCoefficient"]] = relationship(
        back_populates="paragraph"
    )
    technical_coefficient_links: Mapped[list["EnirTechnicalCoefficientParagraph"]] = relationship(
        back_populates="paragraph",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<EnirParagraph {self.code}>"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Состав работ
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
# 5. Состав звена
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
# 6. Нормы (таблица Н.вр. и Расц.)
# ─────────────────────────────────────────────────────────────────────────────
class EnirNorm(Base):
    """
    Одна ячейка таблицы норм.

    row_num      — номер строки таблицы
    work_type    — вид работ (заголовок строки, напр. «Из бутового камня под лопатку»)
    condition    — подусловие (напр. «Ленточные фундаменты»)
    thickness_mm — толщина/размер (если применимо)
    column_label — буква столбца: а, б, в, г …
    norm_time    — Н.вр. (чел-ч на единицу измерения)
    price_rub    — Расц. (руб-коп)
    """
    __tablename__ = "enir_norms"

    id:           Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int]        = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_num:      Mapped[int|None]   = mapped_column(SmallInteger)
    work_type:    Mapped[str|None]   = mapped_column(Text)
    condition:    Mapped[str|None]   = mapped_column(Text)
    thickness_mm: Mapped[int|None]   = mapped_column(Integer)
    column_label: Mapped[str|None]   = mapped_column(String(10))
    norm_time:    Mapped[float|None] = mapped_column(Numeric(10, 4))
    price_rub:    Mapped[float|None] = mapped_column(Numeric(12, 4))

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="norms")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Примечания
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
    conditions:   Mapped[dict|None]  = mapped_column(JSONB)
    formula:      Mapped[str|None]   = mapped_column(Text)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="notes")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Исходные E1-данные, которые не покрываются плоской моделью E3
# ─────────────────────────────────────────────────────────────────────────────
class EnirParagraphTechnicalCharacteristic(Base):
    """Сырые технические характеристики параграфа, как они пришли из E1 JSON."""
    __tablename__ = "enir_paragraph_technical_characteristics"

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order:   Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_text:     Mapped[str] = mapped_column(Text, nullable=False)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="technical_characteristics")


class EnirParagraphApplicationNote(Base):
    """Примечания по применению нормы, отдельные от нормативных примечаний."""
    __tablename__ = "enir_paragraph_application_notes"

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order:   Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text:         Mapped[str] = mapped_column(Text, nullable=False)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="application_notes")


class EnirParagraphRef(Base):
    """Ссылка, связанная с параграфом ENIR."""
    __tablename__ = "enir_paragraph_refs"

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order:   Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ref_type:     Mapped[str] = mapped_column(String(20), nullable=False)
    link_text:    Mapped[str|None] = mapped_column(Text)
    href:         Mapped[str|None] = mapped_column(Text)
    abs_url:      Mapped[str|None] = mapped_column(Text)
    context_text: Mapped[str|None] = mapped_column(Text)
    is_meganorm:  Mapped[bool|None] = mapped_column(Boolean, default=False)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="paragraph_refs")


class EnirSourceWorkItem(Base):
    """Исходный блок состава работ из E1 в неизменённом виде."""
    __tablename__ = "enir_source_work_items"

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order:   Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_text:     Mapped[str] = mapped_column(Text, nullable=False)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="source_work_items")


class EnirSourceCrewItem(Base):
    """Исходная запись состава звена из E1 с raw-представлением."""
    __tablename__ = "enir_source_crew_items"

    id:           Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int]        = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order:   Mapped[int]        = mapped_column(Integer, default=0, nullable=False)
    profession:   Mapped[str|None]   = mapped_column(String(200))
    grade:        Mapped[float|None] = mapped_column(Numeric(4, 1))
    count:        Mapped[int|None]   = mapped_column(SmallInteger)
    raw_text:     Mapped[str|None]   = mapped_column(Text)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="source_crew_items")


class EnirSourceNote(Base):
    """Исходная запись примечания из E1 с item_order/code/coefficient."""
    __tablename__ = "enir_source_notes"

    id:           Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int]        = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order:   Mapped[int]        = mapped_column(Integer, default=0, nullable=False)
    code:         Mapped[str|None]   = mapped_column(String(20))
    text:         Mapped[str]        = mapped_column(Text, nullable=False)
    coefficient:  Mapped[float|None] = mapped_column(Numeric(6, 4))
    conditions:   Mapped[dict|None]  = mapped_column(JSONB)
    formula:      Mapped[str|None]   = mapped_column(Text)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="source_notes")


class EnirNormTable(Base):
    """Таблица норм E1 в исходной сеточной форме."""
    __tablename__ = "enir_norm_tables"

    id:              Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paragraph_id:    Mapped[int]      = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_table_id: Mapped[str]      = mapped_column(String(120), nullable=False, unique=True)
    sort_order:      Mapped[int]      = mapped_column(Integer, default=0, nullable=False)
    title:           Mapped[str|None] = mapped_column(Text)
    row_count:       Mapped[int|None] = mapped_column(Integer)

    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="norm_tables")
    columns: Mapped[list["EnirNormColumn"]] = relationship(
        back_populates="norm_table", cascade="all, delete-orphan", order_by="EnirNormColumn.sort_order"
    )
    rows: Mapped[list["EnirNormRow"]] = relationship(
        back_populates="norm_table", cascade="all, delete-orphan", order_by="EnirNormRow.sort_order"
    )


class EnirNormColumn(Base):
    """Колонка таблицы норм E1."""
    __tablename__ = "enir_norm_columns"
    __table_args__ = (
        UniqueConstraint("norm_table_id", "source_column_key", name="uq_enir_norm_column_key"),
    )

    id:                Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    norm_table_id:     Mapped[int]      = mapped_column(
        BigInteger, ForeignKey("enir_norm_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_column_key: Mapped[str]      = mapped_column(Text, nullable=False)
    sort_order:        Mapped[int]      = mapped_column(Integer, default=0, nullable=False)
    header:            Mapped[str]      = mapped_column(Text, nullable=False)
    label:             Mapped[str|None] = mapped_column(Text)

    norm_table: Mapped["EnirNormTable"] = relationship(back_populates="columns")
    values: Mapped[list["EnirNormValue"]] = relationship(
        back_populates="norm_column", cascade="all, delete-orphan"
    )


class EnirNormRow(Base):
    """Строка таблицы норм E1."""
    __tablename__ = "enir_norm_rows"

    id:            Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    norm_table_id: Mapped[int]      = mapped_column(
        BigInteger, ForeignKey("enir_norm_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_row_id: Mapped[str]      = mapped_column(String(140), nullable=False, unique=True)
    sort_order:    Mapped[int]      = mapped_column(Integer, default=0, nullable=False)
    source_row_num: Mapped[int|None] = mapped_column(SmallInteger)
    params:        Mapped[dict|None] = mapped_column(JSONB)

    norm_table: Mapped["EnirNormTable"] = relationship(back_populates="rows")
    values: Mapped[list["EnirNormValue"]] = relationship(
        back_populates="norm_row", cascade="all, delete-orphan"
    )


class EnirNormValue(Base):
    """Значение ячейки E1, включая отдельные price_cell записи."""
    __tablename__ = "enir_norm_values"

    id:             Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    norm_row_id:    Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_norm_rows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    norm_column_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_norm_columns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value_type:     Mapped[str] = mapped_column(String(30), nullable=False)
    value_text:     Mapped[str|None] = mapped_column(Text)
    value_numeric:  Mapped[float|None] = mapped_column(Numeric(12, 4))

    norm_row: Mapped["EnirNormRow"] = relationship(back_populates="values")
    norm_column: Mapped["EnirNormColumn"] = relationship(back_populates="values")


class EnirTechnicalCoefficient(Base):
    """Машиночитаемый технический коэффициент с областью применения от сборника до параграфа."""
    __tablename__ = "enir_technical_coefficients"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(section_id, chapter_id, paragraph_id) <= 1",
            name="ck_enir_tc_one_scope",
        ),
        Index("ix_enir_tc_collection_id", "collection_id"),
        Index(
            "ix_enir_tc_section_id",
            "section_id",
            postgresql_where=text("section_id IS NOT NULL"),
        ),
        Index(
            "ix_enir_tc_chapter_id",
            "chapter_id",
            postgresql_where=text("chapter_id IS NOT NULL"),
        ),
        Index(
            "ix_enir_tc_paragraph_id",
            "paragraph_id",
            postgresql_where=text("paragraph_id IS NOT NULL"),
        ),
    )

    id:            Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enir_collections.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[int|None] = mapped_column(
        BigInteger, ForeignKey("enir_sections.id", ondelete="CASCADE")
    )
    chapter_id: Mapped[int|None] = mapped_column(
        BigInteger, ForeignKey("enir_chapters.id", ondelete="CASCADE")
    )
    paragraph_id: Mapped[int|None] = mapped_column(
        BigInteger, ForeignKey("enir_paragraphs.id", ondelete="CASCADE")
    )
    code:        Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    multiplier:  Mapped[float|None] = mapped_column(Numeric(8, 4))
    conditions:  Mapped[dict|None] = mapped_column(JSONB)
    formula:     Mapped[str|None] = mapped_column(Text)
    sort_order:  Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    collection: Mapped["EnirCollection"] = relationship(back_populates="technical_coefficients")
    section: Mapped["EnirSection | None"] = relationship(back_populates="technical_coefficients")
    chapter: Mapped["EnirChapter | None"] = relationship(back_populates="technical_coefficients")
    paragraph: Mapped["EnirParagraph | None"] = relationship(back_populates="technical_coefficients")
    paragraph_links: Mapped[list["EnirTechnicalCoefficientParagraph"]] = relationship(
        back_populates="technical_coefficient",
        cascade="all, delete-orphan",
    )


class EnirTechnicalCoefficientParagraph(Base):
    """Связка технического коэффициента с конкретными параграфами, когда область применения — список."""
    __tablename__ = "enir_technical_coefficient_paragraphs"

    technical_coefficient_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("enir_technical_coefficients.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paragraph_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("enir_paragraphs.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    technical_coefficient: Mapped["EnirTechnicalCoefficient"] = relationship(
        back_populates="paragraph_links"
    )
    paragraph: Mapped["EnirParagraph"] = relationship(back_populates="technical_coefficient_links")
