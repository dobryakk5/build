# backend/app/models/ktp.py
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class KtpGroup(Base, TimestampMixin):
    """Группа работ, выделенная из блока сметы."""

    __tablename__ = "ktp_groups"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    estimate_batch_id: Mapped[str] = mapped_column(
        ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False
    )
    # Ключ группы: section / fer_group_title / slugified fallback
    # Используется для идемпотентного пересоздания групп.
    group_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # id строк сметы, вошедших в группу
    estimate_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_price: Mapped[float | None] = mapped_column(Numeric(16, 2))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # new | questions_required | generated | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="new")

    # lazy="selectin" — ktp_card грузится вместе с группой без N+1
    ktp_card: Mapped["KtpCard | None"] = relationship(
        back_populates="ktp_group",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class KtpCard(Base, TimestampMixin):
    """КТП (Карта Технологического Процесса) по одной группе работ."""

    __tablename__ = "ktp_cards"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    estimate_batch_id: Mapped[str] = mapped_column(
        ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False
    )
    ktp_group_id: Mapped[str] = mapped_column(
        ForeignKey("ktp_groups.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    title: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(Text)
    # [{no, stage, work_details, control_points}, ...]
    steps_json: Mapped[list | None] = mapped_column(JSONB)
    # ["рекомендация 1", ...]
    recommendations_json: Mapped[list | None] = mapped_column(JSONB)
    # [{key, label, type, hint?, options?}, ...] — вопросы от LLM
    questions_json: Mapped[list | None] = mapped_column(JSONB)
    # {key: answer_text} — ответы пользователя
    answers_json: Mapped[dict | None] = mapped_column(JSONB)
    llm_model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    # draft | questions_required | generated | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    error_message: Mapped[str | None] = mapped_column(Text)

    ktp_group: Mapped["KtpGroup"] = relationship(back_populates="ktp_card")
