from datetime import datetime, date
import uuid
from sqlalchemy import String, Text, Date, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import TIMESTAMP
TIMESTAMPTZ = TIMESTAMP(timezone=True)
from .base import Base, TimestampMixin, SoftDeleteMixin


class Project(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    id:               Mapped[str]       = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id:  Mapped[str]       = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by:       Mapped[str|None]  = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name:             Mapped[str]       = mapped_column(String(255), nullable=False)
    address:          Mapped[str|None]  = mapped_column(Text)
    # active | paused | done | archived
    status:           Mapped[str]       = mapped_column(String(20), default="active", nullable=False)
    color:            Mapped[str|None]  = mapped_column(String(20))
    start_date:       Mapped[date|None] = mapped_column(Date)
    end_date:         Mapped[date|None] = mapped_column(Date)
    # green | yellow | red — обновляется Celery каждое утро
    dashboard_status: Mapped[str]       = mapped_column(String(10), default="green", nullable=False)

    organization: Mapped["Organization"]        = relationship(back_populates="projects")
    members:      Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete")
    gantt_tasks:  Mapped[list["GanttTask"]]     = relationship(back_populates="project")
    estimates:    Mapped[list["Estimate"]]       = relationship(back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_members"

    id:         Mapped[str]      = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str]      = mapped_column(ForeignKey("projects.id",  ondelete="CASCADE"), nullable=False)
    user_id:    Mapped[str]      = mapped_column(ForeignKey("users.id",     ondelete="CASCADE"), nullable=False)
    invited_by: Mapped[str|None] = mapped_column(ForeignKey("users.id",     ondelete="SET NULL"))
    # owner | pm | foreman | supplier | viewer
    role:       Mapped[str]      = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))

    project: Mapped["Project"] = relationship(back_populates="members")
    user:    Mapped["User"]    = relationship(foreign_keys=[user_id])