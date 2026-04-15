# backend/app/api/routes/gantt.py
"""
Fix 3: progress только через отчёт для foreman
Fix 9: все URL через /projects/{pid}/...
Fix 10: working_days везде
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps        import require_action, require_task_in_project, get_project_member, get_db, get_current_user
from app.core.permissions import Action
from app.core.date_utils  import task_end_date
from app.models           import GanttTask, TaskDependency, Comment, Estimate, User, ProjectMember
from app.schemas          import (
    TaskCreate, TaskUpdate, TaskResponse, TaskPatchResponse,
    TaskReorderRequest, GanttResponse, DependencyAdd,
    TaskSplitRequest, TaskSplitResponse,
)
from app.services.gantt_calculations import (
    DEFAULT_HOURS_PER_DAY,
    calculate_labor_hours,
    calculate_working_days,
)
from app.services.gantt_service import (
    accept_overdue_baseline,
    get_baseline_status,
    get_effective_progress, update_leaf_progress,
    resolve_project_dates, reorder_task, soft_delete_task, split_task_by_date,
    _refresh_is_group,
)

router = APIRouter(prefix="/projects/{project_id}/gantt", tags=["gantt"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _estimate_fer_labor_hours(estimate: Estimate | None) -> float | None:
    if estimate is None or estimate.fer_words_human_hours is None:
        return None

    fer_human_hours = float(estimate.fer_words_human_hours)
    if estimate.quantity is None:
        return round(fer_human_hours, 2)

    return round(fer_human_hours * float(estimate.quantity), 2)

async def _enrich_task(task: GanttTask, db: AsyncSession) -> TaskResponse:
    """Добавляет вычисляемые поля к задаче."""

    # Прогресс группы — вычислить, листа — взять stored
    progress = (
        await get_effective_progress(task.id, db)
        if task.is_group else task.progress
    )

    # Дата окончания
    end_date = task_end_date(task.start_date, task.working_days)

    # Зависимости
    deps = await db.scalars(
        select(TaskDependency.depends_on)
        .where(TaskDependency.task_id == task.id)
    )

    # Количество комментариев
    comments_count = await db.scalar(
        select(func.count())
        .select_from(Comment)
        .where(Comment.task_id    == task.id)
        .where(Comment.deleted_at == None)
    )

    # Исполнитель
    assignee = None
    if task.assignee_id:
        u = await db.get(User, task.assignee_id)
        if u:
            assignee = {"id": u.id, "name": u.name, "avatar_url": u.avatar_url}
    estimate = await db.get(Estimate, task.estimate_id) if task.estimate_id else None

    return TaskResponse(
        id             = task.id,
        project_id     = task.project_id,
        estimate_batch_id = task.estimate_batch_id,
        parent_id      = task.parent_id,
        estimate_id    = task.estimate_id,
        name           = task.name,
        start_date     = task.start_date,
        working_days   = task.working_days,
        workers_count  = task.workers_count,
        labor_hours    = float(task.labor_hours) if task.labor_hours is not None else None,
        fer_labor_hours = _estimate_fer_labor_hours(estimate),
        hours_per_day  = float(task.hours_per_day or DEFAULT_HOURS_PER_DAY),
        end_date       = end_date,
        progress       = progress,
        is_group       = task.is_group,
        type           = task.type,
        color          = task.color,
        requires_act   = task.requires_act,
        act_signed     = task.act_signed,
        req_hidden_work_act = estimate.req_hidden_work_act if estimate else False,
        req_intermediate_act = estimate.req_intermediate_act if estimate else False,
        req_ks2_ks3 = estimate.req_ks2_ks3 if estimate else False,
        row_order      = float(task.row_order),
        assignee       = assignee,
        depends_on     = ",".join(list(deps)),
        materials      = estimate.materials or [] if estimate else [],
        comments_count = comments_count or 0,
    )


class BaselineAcceptRequest(BaseModel):
    reason: str | None = None


# ── GET /projects/{pid}/gantt ─────────────────────────────────────────────────

@router.get("", response_model=GanttResponse)
async def list_tasks(
    project_id: UUID,
    estimate_batch_id: UUID | None = Query(default=None),
    limit:  int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    total_q = (
        select(func.count()).select_from(GanttTask)
        .where(GanttTask.project_id == str(project_id))
        .where(GanttTask.deleted_at == None)
    )
    tasks_q = (
        select(GanttTask)
        .where(GanttTask.project_id == str(project_id))
        .where(GanttTask.deleted_at == None)
        .order_by(GanttTask.row_order)
    )
    if estimate_batch_id:
        total_q = total_q.where(GanttTask.estimate_batch_id == str(estimate_batch_id))
        tasks_q = tasks_q.where(GanttTask.estimate_batch_id == str(estimate_batch_id))
    tasks_q = tasks_q.limit(limit).offset(offset)

    total = await db.scalar(total_q)

    tasks = await db.scalars(
        tasks_q
    )

    enriched = [await _enrich_task(t, db) for t in tasks]

    return GanttResponse(
        tasks    = enriched,
        total    = total or 0,
        has_more = (offset + limit) < (total or 0),
    )


# ── POST /projects/{pid}/gantt ────────────────────────────────────────────────

@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    project_id: UUID,
    body: TaskCreate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    from uuid import uuid4

    estimate_batch_id = None
    if body.parent_id:
        parent = await db.get(GanttTask, body.parent_id)
        estimate_batch_id = parent.estimate_batch_id if parent else None

    is_group_task = body.type == "project"
    workers_count = None if is_group_task else max(1, int(body.workers_count or 1))
    hours_per_day = float(body.hours_per_day or DEFAULT_HOURS_PER_DAY)
    labor_hours = None if is_group_task else body.labor_hours
    working_days = body.working_days or 1

    if not is_group_task:
        if labor_hours is not None:
            working_days = calculate_working_days(labor_hours, workers_count, hours_per_day) or 1
        else:
            labor_hours = calculate_labor_hours(working_days, workers_count, hours_per_day)

    task = GanttTask(
        id           = str(uuid4()),
        project_id   = str(project_id),
        estimate_batch_id = estimate_batch_id,
        name         = body.name,
        start_date   = body.start_date,
        working_days = working_days,
        workers_count = workers_count,
        labor_hours  = labor_hours,
        hours_per_day = hours_per_day,
        parent_id    = body.parent_id,
        assignee_id  = body.assignee_id,
        type         = body.type,
        color        = body.color,
        requires_act = body.requires_act,
        row_order    = body.row_order,
        is_group     = is_group_task,
        progress     = 0,
    )
    db.add(task)

    # Обновляем is_group родителя
    if body.parent_id:
        await _refresh_is_group(body.parent_id, db)

    await db.commit()
    await db.refresh(task)
    return await _enrich_task(task, db)


# ── PATCH /projects/{pid}/gantt/{tid} ─────────────────────────────────────────

@router.patch("/{task_id}", response_model=TaskPatchResponse)
async def update_task(
    project_id: UUID,
    task_id: UUID,
    body: TaskUpdate,
    current_user = Depends(get_current_user),
    member_and_task = Depends(require_task_in_project(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    member, task = member_and_task

    # Fix 3: foreman не может PATCH задачу напрямую совсем
    if member.role == "foreman":
        raise HTTPException(
            403,
            "Прораб может изменять прогресс только через ежедневный отчёт"
        )

    update_fields = body.model_dump(exclude_unset=True)

    # PM не может переопределить прогресс если есть незакрытый черновик отчёта
    if "progress_override" in update_fields and member.role == "pm":
        from app.models import DailyReport
        open_report = await db.scalar(
            select(DailyReport)
            .join(DailyReport.items)
            .where(DailyReport.project_id == str(project_id))
            .where(DailyReport.status     == "draft")
        )
        if open_report:
            raise HTTPException(
                409,
                "Есть черновик отчёта прораба — прогресс будет обновлён при его отправке"
            )

    schedule_fields = {"working_days", "workers_count", "labor_hours", "hours_per_day"}

    # Применяем изменения
    dates_changed = False
    for field, value in update_fields.items():
        if field == "progress_override":
            # owner/pm могут форсировать прогресс
            if not task.is_group:
                await update_leaf_progress(task, value, current_user.id, db)
        else:
            setattr(task, field, value)
            if field in ("start_date", "working_days") or field in schedule_fields:
                dates_changed = True

    if not task.is_group:
        workers_count = max(1, int(task.workers_count or 1))
        hours_per_day = float(task.hours_per_day or DEFAULT_HOURS_PER_DAY)

        if any(field in update_fields for field in ("labor_hours", "workers_count", "hours_per_day")):
            task.workers_count = workers_count
            task.hours_per_day = hours_per_day
            task.working_days = calculate_working_days(task.labor_hours, workers_count, hours_per_day) or 1
        elif "working_days" in update_fields:
            task.workers_count = workers_count
            task.hours_per_day = hours_per_day
            task.labor_hours = calculate_labor_hours(task.working_days, workers_count, hours_per_day)
    else:
        task.workers_count = None
        task.labor_hours = None

    await db.flush()

    # Пересчитываем зависимые задачи при изменении дат
    affected = []
    if dates_changed:
        affected = await resolve_project_dates(str(project_id), db)

    await db.commit()
    await db.refresh(task)

    return TaskPatchResponse(
        task           = await _enrich_task(task, db),
        affected_tasks = affected,
    )


@router.post("/{task_id}/split", response_model=TaskSplitResponse)
async def split_task(
    project_id: UUID,
    task_id: UUID,
    body: TaskSplitRequest,
    current_user = Depends(get_current_user),
    member_and_task = Depends(require_task_in_project(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    _, task = member_and_task

    try:
        updated_task, created_task, affected = await split_task_by_date(
            task=task,
            split_date=body.split_date,
            new_workers_count=body.new_workers_count,
            actor_id=current_user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    await db.refresh(updated_task)
    await db.refresh(created_task)

    return TaskSplitResponse(
        updated_task=await _enrich_task(updated_task, db),
        created_task=await _enrich_task(created_task, db),
        affected_tasks=affected,
    )


# ── DELETE /projects/{pid}/gantt/{tid} ────────────────────────────────────────

@router.delete("/{task_id}")
async def delete_task(
    project_id: UUID,
    task_id: UUID,
    current_user = Depends(get_current_user),
    member_and_task = Depends(require_task_in_project(Action.DELETE)),
    db: AsyncSession = Depends(get_db),
):
    member, task = member_and_task
    deleted_ids = await soft_delete_task(task, current_user.id, db)
    await db.commit()
    return {"deleted": deleted_ids}


# ── POST /projects/{pid}/gantt/reorder ────────────────────────────────────────

@router.post("/reorder")
async def reorder(
    project_id: UUID,
    body: TaskReorderRequest,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    task = await reorder_task(
        task_id       = body.task_id,
        after_id      = body.after_id,
        before_id     = body.before_id,
        new_parent_id = body.new_parent_id,
        db            = db,
    )
    await db.commit()
    return {"task_id": task.id, "row_order": float(task.row_order)}


# ── POST /projects/{pid}/gantt/resolve ────────────────────────────────────────

@router.post("/resolve")
async def resolve(
    project_id: UUID,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    changed = await resolve_project_dates(str(project_id), db)
    await db.commit()
    return {"resolved_count": len(changed), "affected": changed}


@router.get("/baseline-status")
async def baseline_status(
    project_id: UUID,
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    status = await get_baseline_status(str(project_id), db)
    latest = status["latest"]
    latest_user = await db.get(User, latest.created_by) if latest and latest.created_by else None

    return {
        "can_accept": member.role == "pm" and status["has_overdue_tasks"] and not status["accepted_this_week"],
        "accepted_this_week": status["accepted_this_week"],
        "current_year": status["current_year"],
        "current_week": status["current_week"],
        "has_overdue_tasks": status["has_overdue_tasks"],
        "overdue_tasks_count": status["overdue_tasks_count"],
        "latest": (
            {
                "id": latest.id,
                "kind": latest.kind,
                "baseline_year": latest.baseline_year,
                "baseline_week": latest.baseline_week,
                "reason": latest.reason,
                "created_at": latest.created_at.isoformat(),
                "created_by": {"id": latest_user.id, "name": latest_user.name} if latest_user else None,
            }
            if latest else None
        ),
    }


@router.post("/accept-overdue", status_code=201)
async def accept_overdue(
    project_id: UUID,
    body: BaselineAcceptRequest,
    current_user = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    if member.role != "pm":
        raise HTTPException(403, "Только руководитель проекта может принять просроченный график как текущий")

    try:
        baseline = await accept_overdue_baseline(
            project_id=str(project_id),
            actor_id=current_user.id,
            reason=body.reason.strip() if body.reason else None,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    await db.commit()
    return {
        "id": baseline.id,
        "kind": baseline.kind,
        "baseline_year": baseline.baseline_year,
        "baseline_week": baseline.baseline_week,
        "created_at": baseline.created_at.isoformat(),
    }


# ── Зависимости задач ─────────────────────────────────────────────────────────

@router.post("/{task_id}/dependencies")
async def add_dependency(
    project_id: UUID,
    task_id: UUID,
    body: DependencyAdd,
    member_and_task = Depends(require_task_in_project(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    _, task = member_and_task
    if body.depends_on == str(task_id):
        raise HTTPException(400, "Задача не может зависеть от самой себя")

    # Проверяем что предшественник тоже из этого проекта
    pred = await db.scalar(
        select(GanttTask)
        .where(GanttTask.id         == body.depends_on)
        .where(GanttTask.project_id == str(project_id))
        .where(GanttTask.deleted_at == None)
    )
    if not pred:
        raise HTTPException(404, "Задача-предшественник не найдена")

    from app.models import TaskDependency
    dep = TaskDependency(task_id=str(task_id), depends_on=body.depends_on)
    db.add(dep)

    # Пересчитываем даты
    await resolve_project_dates(str(project_id), db)
    await db.commit()
    return {"task_id": str(task_id), "depends_on": body.depends_on}


@router.delete("/{task_id}/dependencies/{dep_id}")
async def remove_dependency(
    project_id: UUID,
    task_id: UUID,
    dep_id: str,
    member_and_task = Depends(require_task_in_project(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    from app.models import TaskDependency
    dep = await db.get(TaskDependency, (str(task_id), dep_id))
    if dep:
        await db.delete(dep)

    await resolve_project_dates(str(project_id), db)
    await db.commit()
    return {"deleted": True}
