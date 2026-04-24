from datetime import date, datetime
import uuid

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import TIMESTAMP

from .base import Base


TIMESTAMPTZ = TIMESTAMP(timezone=True)


class ForemanTaskReport(Base):
    """
    Один экземпляр = один прораб x одна задача x один день.

    Relationships намеренно не объявлены: в async SQLAlchemy проект
    последовательно использует явные select()/db.get() вместо lazy load.
    """

    __tablename__ = "foreman_task_reports"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("gantt_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    foreman_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    note: Mapped[str | None] = mapped_column(Text)
    email_sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    responded_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        server_default=sa_text("NOW()"),
    )
