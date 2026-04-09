from datetime import date, datetime
import uuid

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy import TIMESTAMP
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class ScheduleBaseline(Base):
    __tablename__ = "schedule_baselines"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted_overdue")
    baseline_year: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_week: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"), nullable=False)


class ScheduleBaselineTask(Base):
    __tablename__ = "schedule_baseline_tasks"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    baseline_id: Mapped[str] = mapped_column(ForeignKey("schedule_baselines.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("gantt_tasks.id", ondelete="SET NULL"))
    estimate_id: Mapped[str | None] = mapped_column(ForeignKey("estimates.id", ondelete="SET NULL"))
    estimate_batch_id: Mapped[str | None] = mapped_column(ForeignKey("estimate_batches.id", ondelete="SET NULL"))
    parent_id: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    working_days: Mapped[int] = mapped_column(Integer, nullable=False)
    workers_count: Mapped[int | None] = mapped_column(SmallInteger)
    labor_hours: Mapped[float | None] = mapped_column(Numeric(10, 2))
    hours_per_day: Mapped[float | None] = mapped_column(Numeric(6, 2))
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20))
    row_order: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    depends_on: Mapped[str | None] = mapped_column(Text)
