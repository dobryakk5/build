from datetime import datetime
import uuid
from sqlalchemy import String, Text, Integer, Numeric, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ
from .base import Base, SoftDeleteMixin


class Estimate(Base, SoftDeleteMixin):
    __tablename__ = "estimates"

    id:          Mapped[str]        = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id:  Mapped[str]        = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    section:     Mapped[str|None]   = mapped_column(String(255))           # «Кровля», «Фундамент»
    work_name:   Mapped[str]        = mapped_column(Text, nullable=False)
    unit:        Mapped[str|None]   = mapped_column(String(50))            # м², м³, шт
    quantity:    Mapped[float|None] = mapped_column(Numeric(12, 3))
    unit_price:  Mapped[float|None] = mapped_column(Numeric(12, 2))
    total_price: Mapped[float|None] = mapped_column(Numeric(14, 2))
    enir_code:   Mapped[str|None]   = mapped_column(String(50))            # код ЕНиР / ГЭСН
    labor_hours: Mapped[float|None] = mapped_column(Numeric(10, 2))        # трудоёмкость чел/час
    row_order:   Mapped[int]        = mapped_column(Integer, default=0)
    raw_data:    Mapped[dict|None]  = mapped_column(JSONB)                 # исходная строка Excel
    created_at:  Mapped[datetime]   = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))

    project:    Mapped["Project"]          = relationship(back_populates="estimates")
    gantt_task: Mapped["GanttTask|None"]   = relationship(back_populates="estimate")
