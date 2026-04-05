# backend/app/schemas/__init__.py

# ── Общие ─────────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field, ConfigDict
from datetime import date, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

T = TypeVar("T")

class PaginatedResponse(BaseModel, Generic[T]):
    items:    list[T]
    total:    int
    limit:    int
    offset:   int
    has_more: bool


class UserShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:         str
    name:       str
    avatar_url: str | None = None
    role:       str | None = None   # роль в контексте проекта


# ── Задачи Ганта ──────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    name:         str       = Field(min_length=1, max_length=500)
    start_date:   date
    working_days: int       = Field(ge=1, le=3650)
    workers_count: int | None = Field(default=1, ge=1, le=500)
    parent_id:    str | None = None
    assignee_id:  str | None = None
    type:         str       = Field(default="task", pattern="^(task|project|milestone)$")
    color:        str | None = None
    requires_act: bool      = False
    row_order:    float     = 1000


class TaskUpdate(BaseModel):
    """
    Все поля опциональные — PATCH семантика.
    Поле progress намеренно отсутствует:
      - для PM/owner — через поле progress_override
      - для foreman  — только через ежедневный отчёт
    """
    name:             str | None  = None
    start_date:       date | None = None
    working_days:     int | None  = Field(default=None, ge=1)
    workers_count:    int | None  = Field(default=None, ge=1, le=500)
    parent_id:        str | None  = None
    assignee_id:      str | None  = None
    color:            str | None  = None
    requires_act:     bool | None = None
    act_signed:       bool | None = None
    # Только owner/pm могут использовать это поле напрямую
    progress_override: int | None = Field(default=None, ge=0, le=100)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:           str
    project_id:   str
    estimate_batch_id: str | None
    parent_id:    str | None
    estimate_id:  str | None
    name:         str
    start_date:   date
    working_days: int
    workers_count: int | None
    end_date:     date         # вычисляется в сервисе
    progress:     int          # для группы — вычисленный, для листа — stored
    is_group:     bool
    type:         str
    color:        str | None
    requires_act: bool
    act_signed:   bool
    row_order:    float
    assignee:     UserShort | None = None
    depends_on:   str = ""  # comma-separated IDs, совместимо с Gantt-страницей
    comments_count: int = 0


class TaskReorderRequest(BaseModel):
    task_id:       str
    after_id:      str | None = None   # вставить после этой задачи
    before_id:     str | None = None   # вставить перед этой задачей
    new_parent_id: str | None = None   # None = оставить как есть


class GanttResponse(BaseModel):
    tasks:          list[TaskResponse]
    total:          int
    has_more:       bool = False


class TaskPatchResponse(BaseModel):
    task:           TaskResponse
    affected_tasks: list[dict]  # [{id, start_date}] — что сдвинулось


class TaskSplitRequest(BaseModel):
    split_date: date
    new_workers_count: int = Field(ge=1, le=500)


class TaskSplitResponse(BaseModel):
    updated_task: TaskResponse
    created_task: TaskResponse
    affected_tasks: list[dict]


# ── Зависимости ───────────────────────────────────────────────────────────────

class DependencyAdd(BaseModel):
    depends_on: str   # ID предшественника

class DependencyRemove(BaseModel):
    depends_on: str


# ── Комментарии ───────────────────────────────────────────────────────────────

class CommentCreate(BaseModel):
    text:        str  = Field(min_length=1)
    attachments: list[dict] = []

class CommentUpdate(BaseModel):
    text: str = Field(min_length=1)

class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:          str
    task_id:     str
    author:      UserShort
    author_role: str
    text:        str
    attachments: list[dict]
    edited_at:   datetime | None
    created_at:  datetime


# ── Смета ────────────────────────────────────────────────────────────────────

class EstimateRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:          str
    estimate_batch_id: str | None
    section:     str | None
    work_name:   str
    unit:        str | None
    quantity:    float | None
    unit_price:  float | None
    total_price: float | None
    enir_code:   str | None
    fer_table_id: int | None
    fer_work_type: str | None
    fer_match_score: float | None

class EstimateSummary(BaseModel):
    total:    float
    sections: list[dict]   # [{name, subtotal, items}]


class EstimateBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    estimate_kind: str
    source_filename: str | None = None
    estimates_count: int = 0
    gantt_tasks_count: int = 0
    fer_matched_count: int = 0
    total_price: float = 0
    created_at: datetime


# ── Jobs ─────────────────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:          str
    type:        str
    status:      str       # pending | processing | done | failed
    result:      dict | None = None
    started_at:  datetime | None
    finished_at: datetime | None
    created_at:  datetime


class UploadStartResponse(BaseModel):
    job_id:  str
    message: str = "Файл принят в обработку. Используйте job_id для проверки статуса."


class JobStartResponse(BaseModel):
    job_id:  str
    message: str = "Задача поставлена в очередь. Используйте job_id для проверки статуса."


# ── Отчёты ───────────────────────────────────────────────────────────────────

class ReportItemCreate(BaseModel):
    task_id:        str
    work_done:      str = Field(min_length=1)
    volume_done:    float | None = None
    volume_unit:    str | None   = None
    progress_after: int = Field(ge=0, le=100)
    workers_count:  int | None   = None
    workers_note:   str | None   = None
    materials_used: list[dict]   = []

class ReportCreate(BaseModel):
    report_date: date
    summary:     str | None = None
    issues:      str | None = None
    weather:     str | None = None
    items:       list[ReportItemCreate] = []

class ReportItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:             str
    task_id:        str
    task_name:      str     # JOIN при выдаче
    work_done:      str
    volume_done:    float | None
    volume_unit:    str | None
    progress_after: int
    workers_count:  int | None

class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:           str
    project_id:   str
    author:       UserShort
    report_date:  date
    status:       str
    summary:      str | None
    issues:       str | None
    weather:      str | None
    items:        list[ReportItemResponse]
    submitted_at: datetime | None
    created_at:   datetime

class ReportTodayStatus(BaseModel):
    date:    date
    foremen: list[dict]   # [{foreman: UserShort, submitted: bool, report_id: str|None}]


# ── Уведомления ──────────────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:          str
    type:        str
    title:       str
    body:        str | None
    entity_type: str | None
    entity_id:   str | None
    is_read:     bool
    created_at:  datetime
