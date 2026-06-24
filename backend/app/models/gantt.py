from datetime import datetime, date
import uuid
from sqlalchemy import String, Text, Date, Integer, SmallInteger, Boolean, Numeric, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import TIMESTAMP
TIMESTAMPTZ = TIMESTAMP(timezone=True)
from .base import Base, TimestampMixin, SoftDeleteMixin


class GanttTask(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "gantt_tasks"

    id:           Mapped[str]       = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id:   Mapped[str]       = mapped_column(ForeignKey("projects.id",     ondelete="CASCADE"), nullable=False)
    estimate_batch_id: Mapped[str | None] = mapped_column(ForeignKey("estimate_batches.id", ondelete="SET NULL"))
    estimate_id:  Mapped[str|None]  = mapped_column(ForeignKey("estimates.id",    ondelete="SET NULL"))
    parent_id:    Mapped[str|None]  = mapped_column(ForeignKey("gantt_tasks.id",  ondelete="SET NULL"))
    assignee_id:  Mapped[str|None]  = mapped_column(ForeignKey("users.id",        ondelete="SET NULL"))

    name:         Mapped[str]       = mapped_column(Text, nullable=False)
    start_date:   Mapped[date]      = mapped_column(Date, nullable=False)
    working_days: Mapped[int]       = mapped_column(Integer, nullable=False)
    workers_count: Mapped[int|None] = mapped_column(SmallInteger)
    labor_hours: Mapped[float|None] = mapped_column(Numeric(10, 2))
    hours_per_day: Mapped[float]    = mapped_column(Numeric(6, 2), nullable=False, server_default=text("8"))
    # Хранится только у листовых задач (is_group=False).
    # У групп — вычисляется через get_effective_progress() как взвешенное среднее
    progress:     Mapped[int]       = mapped_column(SmallInteger, default=0)
    # True если имеет дочерние задачи — обновляется при изменении дерева
    is_group:     Mapped[bool]      = mapped_column(Boolean, default=False)
    # task | project | milestone
    type:         Mapped[str]       = mapped_column(String(20), default="task")
    color:        Mapped[str|None]  = mapped_column(String(20))
    requires_act: Mapped[bool]      = mapped_column(Boolean, default=False)  # акт скрытых работ
    act_signed:   Mapped[bool]      = mapped_column(Boolean, default=False)
    # Fix 7: NUMERIC позволяет midpoint-вставку без UPDATE соседей
    row_order:    Mapped[float]     = mapped_column(Numeric(20, 10), default=1000)
    task_kind: Mapped[str | None] = mapped_column(String(32))
    source_row_key: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    projection_id: Mapped[str | None] = mapped_column(String(96))
    stage_instance_id: Mapped[str | None] = mapped_column(String(255))
    template_stage_number: Mapped[str | None] = mapped_column(String(64))
    stage_number: Mapped[str | None] = mapped_column(String(64))
    canonical_stage_id: Mapped[str | None] = mapped_column(String(255))
    floor_number: Mapped[int | None] = mapped_column(Integer)
    floor_kind: Mapped[str | None] = mapped_column(String(32))
    floor_label: Mapped[str | None] = mapped_column(String(128))
    floor_component: Mapped[str | None] = mapped_column(String(64))
    component_role: Mapped[str | None] = mapped_column(String(128))
    operation_code: Mapped[str | None] = mapped_column(String(128))
    operation_package_code: Mapped[str | None] = mapped_column(String(128))
    semantic_stage_option_id: Mapped[str | None] = mapped_column(String(128))
    stage_option_source: Mapped[str | None] = mapped_column(String(64))
    work_scope_key: Mapped[str | None] = mapped_column(String(255))
    applicability_hash: Mapped[str | None] = mapped_column(String(64))
    applicability_hash_version: Mapped[int | None] = mapped_column(SmallInteger)
    applicability_schema_version: Mapped[str | None] = mapped_column(String(64))
    projection_metadata: Mapped[dict | None] = mapped_column(JSONB)

    project:        Mapped["Project"]             = relationship(back_populates="gantt_tasks")
    estimate_batch: Mapped["EstimateBatch|None"]  = relationship(back_populates="gantt_tasks")
    estimate:       Mapped["Estimate|None"]       = relationship(back_populates="gantt_task")
    assignee:       Mapped["User|None"]           = relationship(foreign_keys=[assignee_id])
    comments:       Mapped[list["Comment"]]       = relationship(back_populates="task", cascade="all, delete")

    children: Mapped[list["GanttTask"]] = relationship(
        "GanttTask",
        foreign_keys=[parent_id],
        back_populates="parent",
    )
    parent: Mapped["GanttTask|None"] = relationship(
        "GanttTask",
        remote_side="GanttTask.id",
        foreign_keys=[parent_id],
        back_populates="children",
    )


class TaskDependency(Base):
    """
    task_id зависит от depends_on.
    Оба FK CASCADE: удаление любой задачи убирает только связь,
    но не удаляет вторую задачу.
    """
    __tablename__ = "task_dependencies"

    task_id:    Mapped[str] = mapped_column(
        ForeignKey("gantt_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on: Mapped[str] = mapped_column(
        ForeignKey("gantt_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    # Технологический лаг в рабочих днях: successor стартует через lag_days после
    # окончания predecessor (напр. выдержка бетона). 0 = «впритык».
    lag_days:   Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
