from datetime import datetime
import uuid
from sqlalchemy import String, Text, Integer, Numeric, ForeignKey, text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy import TIMESTAMP
TIMESTAMPTZ = TIMESTAMP(timezone=True)
from .base import Base, SoftDeleteMixin


class Estimate(Base, SoftDeleteMixin):
    __tablename__ = "estimates"

    id:          Mapped[str]        = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id:  Mapped[str]        = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    estimate_batch_id: Mapped[str | None] = mapped_column(ForeignKey("estimate_batches.id", ondelete="SET NULL"))
    section:     Mapped[str|None]   = mapped_column(String(255))           # «Кровля», «Фундамент»
    work_name:   Mapped[str]        = mapped_column(Text, nullable=False)
    unit:        Mapped[str|None]   = mapped_column(String(50))            # м², м³, шт
    quantity:    Mapped[float|None] = mapped_column(Numeric(12, 3))
    unit_price:  Mapped[float|None] = mapped_column(Numeric(12, 2))
    total_price: Mapped[float|None] = mapped_column(Numeric(14, 2))
    materials:   Mapped[list[dict]|None] = mapped_column(JSONB)
    enir_code:   Mapped[str|None]   = mapped_column(String(50))            # код ЕНиР / ГЭСН
    fer_table_id: Mapped[int|None]  = mapped_column(Integer)
    fer_work_type: Mapped[str|None] = mapped_column(Text)
    fer_match_score: Mapped[float|None] = mapped_column(Numeric(5, 4))
    fer_matched_at: Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    labor_hours: Mapped[float|None] = mapped_column(Numeric(10, 2))        # трудоёмкость чел/час
    req_hidden_work_act: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    req_intermediate_act: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    req_ks2_ks3: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    row_order:   Mapped[int]        = mapped_column(Integer, default=0)
    raw_data:    Mapped[dict|None]  = mapped_column(JSONB)                 # исходная строка Excel
    created_at:  Mapped[datetime]   = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))

    project:        Mapped["Project"]            = relationship(back_populates="estimates")
    estimate_batch: Mapped["EstimateBatch|None"] = relationship(back_populates="estimates")
    gantt_task:     Mapped["GanttTask|None"]     = relationship(back_populates="estimate")
