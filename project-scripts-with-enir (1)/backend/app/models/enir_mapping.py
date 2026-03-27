"""
Модели маппинга сметы → ЕНИР.

Два уровня:
  EnirGroupMapping    — группа задач Ганта → сборник ЕНИР  (этап 1)
  EnirEstimateMapping — строка сметы → параграф ЕНИР       (этап 2)

Жизненный цикл status:
  ai_suggested → confirmed | rejected | manual
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, ForeignKey, Numeric, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from .base import Base

TIMESTAMPTZ = TIMESTAMP(timezone=True)

# Допустимые статусы
MAPPING_STATUSES = ("ai_suggested", "confirmed", "rejected", "manual")


class EnirGroupMapping(Base):
    """
    Этап 1: верхняя группа Ганта → сборник ЕНИР.

    task_id — корневая группа (is_group=True, parent_id=NULL обычно,
              но может быть и вложенная секция верхнего уровня).
    Одна группа — одна запись (UNIQUE task_id).
    При перезапуске маппинга запись обновляется, не дублируется.
    """
    __tablename__ = "enir_group_mappings"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_enir_group_mapping_task"),
    )

    id:            Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id:    Mapped[str]        = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    task_id:       Mapped[str]        = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("gantt_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("enir_collections.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ai_suggested | confirmed | rejected | manual
    status:       Mapped[str]         = mapped_column(String(20), nullable=False, default="ai_suggested")
    confidence:   Mapped[float | None]= mapped_column(Numeric(4, 3))  # 0.000 – 1.000
    ai_reasoning: Mapped[str | None]  = mapped_column(Text)           # объяснение ИИ
    # Альтернативы если ИИ сомневался: [{collection_id, code, title, confidence}]
    alternatives: Mapped[str | None]  = mapped_column(Text)           # JSON-строка

    created_at:   Mapped[datetime]    = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))
    updated_at:   Mapped[datetime]    = mapped_column(
        TIMESTAMPTZ, server_default=text("NOW()"), onupdate=datetime.utcnow
    )

    task:       Mapped["GanttTask"]          = relationship(foreign_keys=[task_id])
    collection: Mapped["EnirCollection | None"] = relationship()

    # Все estimate-маппинги дочерних строк этой группы
    estimate_mappings: Mapped[list["EnirEstimateMapping"]] = relationship(
        back_populates="group_mapping",
        cascade="all, delete-orphan",
    )


class EnirEstimateMapping(Base):
    """
    Этап 2: строка сметы → параграф ЕНИР.

    Привязана к конкретному group_mapping (знает, какой сборник выбран).
    Одна строка сметы — одна запись (UNIQUE estimate_id).
    """
    __tablename__ = "enir_estimate_mappings"
    __table_args__ = (
        UniqueConstraint("estimate_id", name="uq_enir_estimate_mapping_estimate"),
    )

    id:               Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id:       Mapped[str]        = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    group_mapping_id: Mapped[int]        = mapped_column(
        BigInteger,
        ForeignKey("enir_group_mappings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    estimate_id:      Mapped[str]        = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
    )
    paragraph_id:     Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("enir_paragraphs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Вариант В: текстовая подсказка + слабая ссылка на строку нормы из JSONB-таблицы.
    norm_row_id:      Mapped[str | None] = mapped_column(String(120), nullable=True)
    norm_row_hint:    Mapped[str | None] = mapped_column(Text)   # свободный текст от ИИ

    status:           Mapped[str]        = mapped_column(String(20), nullable=False, default="ai_suggested")
    confidence:       Mapped[float | None] = mapped_column(Numeric(4, 3))
    ai_reasoning:     Mapped[str | None] = mapped_column(Text)
    # Альтернативы: [{paragraph_id, code, title, confidence}]
    alternatives:     Mapped[str | None] = mapped_column(Text)   # JSON-строка

    created_at:       Mapped[datetime]   = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))
    updated_at:       Mapped[datetime]   = mapped_column(
        TIMESTAMPTZ, server_default=text("NOW()"), onupdate=datetime.utcnow
    )

    group_mapping: Mapped["EnirGroupMapping"]    = relationship(back_populates="estimate_mappings")
    estimate:      Mapped["Estimate"]            = relationship(foreign_keys=[estimate_id])
    paragraph:     Mapped["EnirParagraph | None"] = relationship(foreign_keys=[paragraph_id])
