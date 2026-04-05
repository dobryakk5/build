# backend/app/api/routes/gantt.py
"""
Fix 3: progress только через отчёт для foreman
Fix 9: все URL через /projects/{pid}/...
Fix 10: working_days везде
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps        import require_action, require_task_in_project, get_project_member, get_db, get_current_user
from app.core.permissions import Action
from app.core.date_utils  import task_end_date
from app.models           import GanttTask, TaskDependency, Comment, User, ProjectMember
from app.schemas          import (
    TaskCreate, TaskUpdate, TaskResponse, TaskPatchResponse,
    TaskReorderRequest, GanttResponse, DependencyAdd,
    TaskSplitRequest, TaskSplitResponse,
)
from app.services.gantt_service import (
    get_effective_progress, update_leaf_progress,
    resolve_project_dates, reorder_task, soft_delete_task, split_task_by_date,
    _refresh_is_group,
)

router = APIRouter(prefix="/projects/{project_id}/gantt", tags=["gantt"])


# ── Helpers ───────────────────────────────────────────────────────────────────

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
        end_date       = end_date,
        progress       = progress,
        is_group       = task.is_group,
        type           = task.type,
        color          = task.color,
        requires_act   = task.requires_act,
        act_signed     = task.act_signed,
        row_order      = float(task.row_order),
        assignee       = assignee,
        depends_on     = ",".join(list(deps)),
        comments_count = comments_count or 0,
    )


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

    task = GanttTask(
        id           = str(uuid4()),
        project_id   = str(project_id),
        estimate_batch_id = estimate_batch_id,
        name         = body.name,
        start_date   = body.start_date,
        working_days = body.working_days,
        workers_count = body.workers_count if body.type != "project" else None,
        parent_id    = body.parent_id,
        assignee_id  = body.assignee_id,
        type         = body.type,
        color        = body.color,
        requires_act = body.requires_act,
        row_order    = body.row_order,
        is_group     = False,
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

    # Применяем изменения
    dates_changed = False
    for field, value in update_fields.items():
        if field == "progress_override":
            # owner/pm могут форсировать прогресс
            if not task.is_group:
                await update_leaf_progress(task, value, current_user.id, db)
        else:
            setattr(task, field, value)
            if field in ("start_date", "working_days"):
                dates_changed = True

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
