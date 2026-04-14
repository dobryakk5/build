from datetime import datetime
import uuid

from sqlalchemy import ForeignKey, SmallInteger, String, Text
from sqlalchemy import TIMESTAMP
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    estimate_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        server_default=sa_text("NOW()"),
    )

    project: Mapped["Project"] = relationship(back_populates="estimate_batches")
    estimates: Mapped[list["Estimate"]] = relationship(back_populates="estimate_batch")
    gantt_tasks: Mapped[list["GanttTask"]] = relationship(back_populates="estimate_batch")
