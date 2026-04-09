from datetime import date, datetime
import uuid

from sqlalchemy import Date, ForeignKey, Integer, Text
from sqlalchemy import TIMESTAMP
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class MaterialDelayEvent(Base):
    __tablename__ = "material_delay_events"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), nullable=False)
    reported_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    material_name: Mapped[str] = mapped_column(Text, nullable=False)
    old_delivery_date: Mapped[date | None] = mapped_column(Date)
    new_delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_shifted: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reported_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"), nullable=False)
