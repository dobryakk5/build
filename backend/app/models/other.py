## backend/app/models/comment.py
from datetime import datetime
import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy import TIMESTAMP
TIMESTAMPTZ = TIMESTAMP(timezone=True)
from .base import Base, SoftDeleteMixin


class Comment(Base, SoftDeleteMixin):
    __tablename__ = "comments"

    id:          Mapped[str]       = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id:     Mapped[str]       = mapped_column(ForeignKey("gantt_tasks.id", ondelete="CASCADE"), nullable=False)
    author_id:   Mapped[str]       = mapped_column(ForeignKey("users.id",       ondelete="CASCADE"), nullable=False)
    # Роль фиксируется на момент написания — она может измениться позже
    author_role: Mapped[str]       = mapped_column(String(20), nullable=False)
    text:        Mapped[str]       = mapped_column(Text, nullable=False)
    # [{name, url, size, mime}] — файлы в S3
    attachments: Mapped[list]      = mapped_column(JSONB, default=list)
    edited_at:   Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    created_at:  Mapped[datetime]  = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"))

    task:   Mapped["GanttTask"] = relationship(back_populates="comments")
    author: Mapped["User"]      = relationship(foreign_keys=[author_id])


## backend/app/models/history.py
from datetime import datetime
import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from .base import Base


class TaskHistory(Base):
    """
    Аудит изменений задач.
    task_id = SET NULL при удалении — история не теряется,
    project_id остаётся для привязки к проекту.
    """
    __tablename__ = "task_history"

    id:         Mapped[str]        = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    # SET NULL — история сохраняется даже после мягкого удаления задачи
    task_id:    Mapped[str|None]   = mapped_column(ForeignKey("gantt_tasks.id", ondelete="SET NULL"))
    project_id: Mapped[str]        = mapped_column(ForeignKey("projects.id",   ondelete="CASCADE"), nullable=False)
    user_id:    Mapped[str|None]   = mapped_column(ForeignKey("users.id",      ondelete="SET NULL"))
    # created | updated | deleted | progress_changed | restored
    action:     Mapped[str]        = mapped_column(String(50), nullable=False)
    old_data:   Mapped[dict|None]  = mapped_column(JSONB)
    new_data:   Mapped[dict|None]  = mapped_column(JSONB)
    created_at: Mapped[datetime]   = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"))


## backend/app/models/job.py
from datetime import datetime
import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from .base import Base


class Job(Base):
    """Фоновые задачи: парсинг Excel, экспорт, пересчёт."""
    __tablename__ = "jobs"

    id:          Mapped[str]           = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    # estimate_upload | gantt_export | ...
    type:        Mapped[str]           = mapped_column(String(50), nullable=False)
    # pending | processing | done | failed
    status:      Mapped[str]           = mapped_column(String(20), default="pending", nullable=False)
    project_id:  Mapped[str|None]      = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    created_by:  Mapped[str|None]      = mapped_column(ForeignKey("users.id",    ondelete="SET NULL"))
    input:       Mapped[dict|None]     = mapped_column(JSONB)    # параметры: file_key, start_date, workers...
    result:      Mapped[dict|None]     = mapped_column(JSONB)    # итог или {error: "..."}
    started_at:  Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    finished_at: Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    created_at:  Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"))


## backend/app/models/report.py
from datetime import datetime, date
import uuid
from sqlalchemy import String, Text, Date, SmallInteger, Integer, ForeignKey
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from .base import Base, TimestampMixin


class DailyReport(Base, TimestampMixin):
    """Ежедневный отчёт прораба. Один на прораба в день на проект."""
    __tablename__ = "daily_reports"

    id:           Mapped[str]           = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id:   Mapped[str]           = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    author_id:    Mapped[str]           = mapped_column(ForeignKey("users.id",    ondelete="CASCADE"), nullable=False)
    report_date:  Mapped[date]          = mapped_column(Date, nullable=False)
    # draft → submitted → reviewed
    status:       Mapped[str]           = mapped_column(String(20), default="draft", nullable=False)
    summary:      Mapped[str|None]      = mapped_column(Text)
    issues:       Mapped[str|None]      = mapped_column(Text)
    weather:      Mapped[str|None]      = mapped_column(String(100))
    submitted_at: Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    reviewed_by:  Mapped[str|None]      = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at:  Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)

    author:  Mapped["User"]                    = relationship(foreign_keys=[author_id])
    reviewer: Mapped["User|None"]              = relationship(foreign_keys=[reviewed_by])
    items:   Mapped[list["DailyReportItem"]]   = relationship(back_populates="report", cascade="all, delete")


class DailyReportItem(Base):
    """Строка отчёта — одна на каждую задачу."""
    __tablename__ = "daily_report_items"

    id:             Mapped[str]        = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id:      Mapped[str]        = mapped_column(ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False)
    task_id:        Mapped[str]        = mapped_column(ForeignKey("gantt_tasks.id",   ondelete="CASCADE"), nullable=False)
    work_done:      Mapped[str]        = mapped_column(Text, nullable=False)
    volume_done:    Mapped[float|None] = mapped_column()
    volume_unit:    Mapped[str|None]   = mapped_column(String(50))
    # При submit отчёта → обновляет gantt_tasks.progress
    progress_after: Mapped[int]        = mapped_column(SmallInteger, nullable=False)
    workers_count:  Mapped[int|None]   = mapped_column(SmallInteger)
    workers_note:   Mapped[str|None]   = mapped_column(Text)
    materials_used: Mapped[list]       = mapped_column(JSONB, default=list)  # [{name, quantity, unit}]
    created_at:     Mapped[datetime]   = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"))

    report: Mapped["DailyReport"] = relationship(back_populates="items")
    task:   Mapped["GanttTask"]   = relationship(foreign_keys=[task_id])


## backend/app/models/material.py
from datetime import datetime, date
import uuid
from sqlalchemy import String, Text, Integer, Numeric, ForeignKey
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, SoftDeleteMixin


class Material(Base, SoftDeleteMixin):
    """Перечень материалов. small=мелочёвка прораба, major=снабженец."""
    __tablename__ = "materials"

    id:            Mapped[str]        = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id:    Mapped[str]        = mapped_column(ForeignKey("projects.id",    ondelete="CASCADE"), nullable=False)
    task_id:       Mapped[str|None]   = mapped_column(ForeignKey("gantt_tasks.id", ondelete="SET NULL"))
    name:          Mapped[str]        = mapped_column(Text, nullable=False)
    unit:          Mapped[str|None]   = mapped_column(String(50))
    quantity:      Mapped[float|None]
    # small | major
    type:          Mapped[str]        = mapped_column(String(10), default="small", nullable=False)
    order_date:    Mapped[date|None]
    lead_days:     Mapped[int|None]   = mapped_column(Integer)   # срок поставки
    delivery_date: Mapped[date|None]
    # planned | ordered | delivered
    status:        Mapped[str]        = mapped_column(String(20), default="planned")
    supplier_note: Mapped[str|None]   = mapped_column(Text)
    created_at:    Mapped[datetime]   = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"))


## backend/app/models/escalation.py
from datetime import datetime
import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from .base import Base


class Escalation(Base):
    """
    Автоматически создаётся Celery (07:00).
    Через 48ч без решения → escalated → уведомление директору.
    """
    __tablename__ = "escalations"

    id:           Mapped[str]           = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id:   Mapped[str]           = mapped_column(ForeignKey("projects.id",    ondelete="CASCADE"), nullable=False)
    task_id:      Mapped[str|None]      = mapped_column(ForeignKey("gantt_tasks.id", ondelete="SET NULL"))
    # no_report | plan_not_met | overdue | hidden_work_due
    type:         Mapped[str]           = mapped_column(String(50), nullable=False)
    meta:         Mapped[dict]          = mapped_column(JSONB, default=dict)
    # open → escalated (48ч) → resolved
    status:       Mapped[str]           = mapped_column(String(20), default="open", nullable=False)
    detected_at:  Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"))
    escalated_at: Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    resolved_at:  Mapped[datetime|None] = mapped_column(TIMESTAMPTZ)
    resolved_by:  Mapped[str|None]      = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


## backend/app/models/notification.py
from datetime import datetime
import uuid
from sqlalchemy import String, Text, Boolean, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id:          Mapped[str]       = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id:     Mapped[str]       = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # report_reminder | missing_report | escalation | task_overdue |
    # material_due | hidden_work_due | task_assigned | comment_added
    type:        Mapped[str]       = mapped_column(String(50), nullable=False)
    title:       Mapped[str]       = mapped_column(Text, nullable=False)
    body:        Mapped[str|None]  = mapped_column(Text)
    entity_type: Mapped[str|None]  = mapped_column(String(30))  # task | project | escalation
    entity_id:   Mapped[str|None]  = mapped_column(PGUUID(as_uuid=False))
    is_read:     Mapped[bool]      = mapped_column(Boolean, default=False)
    created_at:  Mapped[datetime]  = mapped_column(TIMESTAMPTZ, server_default=sa_text("NOW()"))