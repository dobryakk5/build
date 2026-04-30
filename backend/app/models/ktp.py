from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class KtpGroup(Base, TimestampMixin):
    __tablename__ = "ktp_groups"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "estimate_batch_id",
            "group_key",
            name="uq_ktp_groups_project_batch_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    estimate_batch_id: Mapped[str] = mapped_column(
        ForeignKey("estimate_batches.id", ondelete="CASCADE"), nullable=False
    )
    group_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    estimate_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_price: Mapped[float | None] = mapped_column(Numeric(16, 2))
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="new"
    )

    ktp_card: Mapped["KtpCard | None"] = relationship(
        back_populates="ktp_group",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class KtpCard(Base, TimestampMixin):
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
    steps_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    recommendations_json: Mapped[list[str] | None] = mapped_column(JSONB)
    questions_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    answers_json: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    llm_model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="draft"
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    ktp_group: Mapped["KtpGroup"] = relationship(back_populates="ktp_card")
