"""
backend/app/services/gantt_service.py

Бизнес-логика Ганта:
  - вычисление прогресса группы из детей (SQL CTE, не N+1)
  - топологический пересчёт дат по зависимостям (алгоритм Кана)
  - reorder через midpoint NUMERIC(20,10)
  - мягкое удаление с каскадом потомков
"""
from __future__ import annotations
from collections import defaultdict, deque
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.date_utils import task_end_date, working_days_between
from app.models import GanttTask, TaskDependency, TaskHistory


# ── Прогресс ─────────────────────────────────────────────────────────────────

async def get_effective_progress(task_id: str, db: AsyncSession) -> int:
    """
    Листовая задача → stored progress.
    Группа          → взвешенное среднее по working_days всех листовых потомков.
    Одним SQL CTE — без N+1.
    """
    row = await db.scalar(text("""
        WITH RECURSIVE tree AS (
            SELECT id, parent_id, working_days, progress, is_group
              FROM gantt_tasks
             WHERE id = :root_id AND deleted_at IS NULL
            UNION ALL
            SELECT t.id, t.parent_id, t.working_days, t.progress, t.is_group
              FROM gantt_tasks t
              JOIN tree ON t.parent_id = tree.id
             WHERE t.deleted_at IS NULL
        )
        SELECT
            CASE
                WHEN SUM(working_days) FILTER (WHERE NOT is_group) = 0 THEN 0
                ELSE ROUND(
                    SUM(progress * working_days) FILTER (WHERE NOT is_group)::numeric /
                    SUM(working_days)            FILTER (WHERE NOT is_group)
                )
            END
          FROM tree
         WHERE NOT is_group
    """), {"root_id": task_id})
    return int(row) if row is not None else 0


async def update_leaf_progress(
    task: GanttTask,
    new_progress: int,
    actor_id: str,
    db: AsyncSession,
) -> None:
    """Обновляет прогресс листа и пишет в task_history."""
    if task.is_group:
        raise ValueError("Прогресс группы вычисляется из подзадач — нельзя менять напрямую")

    old = task.progress
    task.progress = new_progress

    db.add(TaskHistory(
        id         = str(uuid4()),
        task_id    = task.id,
        project_id = task.project_id,   # нужен для истории после мягкого удаления задачи
        user_id    = actor_id,
        action     = "progress_changed",
        old_data   = {"progress": old},
        new_data   = {"progress": new_progress},
    ))


# ── Пересчёт дат ─────────────────────────────────────────────────────────────

async def resolve_project_dates(
    project_id: str,
    db: AsyncSession,
    holidays: set[date] | None = None,
) -> list[dict]:
    """
    Пересчитывает start_date всех задач проекта по зависимостям.
    Возвращает список изменённых задач: [{"id": ..., "start_date": ...}].
    """
    if holidays is None:
        holidays = set()

    tasks_result = await db.scalars(
        select(GanttTask)
        .where(GanttTask.project_id == project_id)
        .where(GanttTask.deleted_at == None)
    )
    tasks = list(tasks_result)
    by_id: dict[str, GanttTask] = {t.id: t for t in tasks}

    # Загружаем все зависимости проекта одним запросом
    deps_result = await db.execute(
        select(TaskDependency)
        .where(TaskDependency.task_id.in_(list(by_id.keys())))
    )
    deps = list(deps_result.scalars())

    # Граф: predecessors → successors
    successors:  dict[str, list[str]] = defaultdict(list)
    in_degree:   dict[str, int]       = defaultdict(int)

    for dep in deps:
        if dep.task_id in by_id and dep.depends_on in by_id:
            successors[dep.depends_on].append(dep.task_id)
            in_degree[dep.task_id] += 1

    # Топологическая сортировка (алгоритм Кана)
    queue = deque(t.id for t in tasks if in_degree[t.id] == 0)
    topo_order: list[str] = []
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for succ in successors[node]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    # predecessor_ends[task_id] = [конец каждого предшественника]
    predecessor_ends: dict[str, list[date]] = defaultdict(list)
    for dep in deps:
        if dep.task_id in by_id and dep.depends_on in by_id:
            pred     = by_id[dep.depends_on]
            pred_end = task_end_date(pred.start_date, pred.working_days, holidays)
            predecessor_ends[dep.task_id].append(pred_end)

    changed: list[dict] = []

    for tid in topo_order:
        task = by_id[tid]
        if not predecessor_ends[tid]:
            continue

        earliest = max(predecessor_ends[tid])
        if task.start_date < earliest:
            task.start_date = earliest
            changed.append({"id": tid, "start_date": str(earliest)})
            db.add(task)

        # Передаём дату конца этой задачи дальше по цепочке
        my_end = task_end_date(task.start_date, task.working_days, holidays)
        for succ_id in successors[tid]:
            predecessor_ends[succ_id].append(my_end)

    return changed


# ── Reorder ───────────────────────────────────────────────────────────────────

async def reorder_task(
    task_id: str,
    after_id: str | None,
    before_id: str | None,
    new_parent_id: str | None,
    db: AsyncSession,
) -> GanttTask:
    """
    Вставляет задачу между after и before через midpoint.
    Не требует UPDATE соседей.
    При нехватке места (разница < 0.001) запускает реиндексацию.
    """
    task = await db.get(GanttTask, task_id)
    if not task:
        raise ValueError(f"Задача {task_id} не найдена")

    after_order = 0.0
    if after_id:
        t = await db.get(GanttTask, after_id)
        if t:
            after_order = float(t.row_order)

    before_order = after_order + 2000.0
    if before_id:
        t = await db.get(GanttTask, before_id)
        if t:
            before_order = float(t.row_order)

    if before_order - after_order < 0.001:
        await _reindex_project_tasks(task.project_id, db)
        return await reorder_task(task_id, after_id, before_id, new_parent_id, db)

    task.row_order = (after_order + before_order) / 2

    if new_parent_id is not None:
        old_parent = task.parent_id
        task.parent_id = new_parent_id or None
        if old_parent:
            await _refresh_is_group(old_parent, db)
        if new_parent_id:
            await _refresh_is_group(new_parent_id, db)

    return task


async def split_task_by_date(
    task: GanttTask,
    split_date: date,
    new_workers_count: int,
    actor_id: str,
    db: AsyncSession,
) -> tuple[GanttTask, GanttTask, list[dict]]:
    """
    Делит листовую задачу на две последовательные части.
    Исходная задача становится первой частью, новая задача — второй.
    """
    if task.deleted_at is not None:
        raise ValueError("Нельзя разделить удалённую задачу")
    if task.is_group:
        raise ValueError("Можно разделять только листовые задачи")

    first_days = working_days_between(task.start_date, split_date)
    if first_days <= 0 or first_days >= task.working_days:
        raise ValueError("Дата разделения должна попадать внутрь интервала задачи")

    second_days = task.working_days - first_days
    original_name = task.name
    original_workers = task.workers_count or 1

    next_order = await _get_next_row_order(task, db)
    if next_order - float(task.row_order) < 0.001:
        await _reindex_project_tasks(task.project_id, db)
        await db.refresh(task)
        next_order = await _get_next_row_order(task, db)

    second_task = GanttTask(
        id=str(uuid4()),
        project_id=task.project_id,
        estimate_batch_id=task.estimate_batch_id,
        estimate_id=task.estimate_id,
        parent_id=task.parent_id,
        assignee_id=task.assignee_id,
        name=f"{original_name} (этап 2)",
        start_date=split_date,
        working_days=second_days,
        workers_count=new_workers_count,
        progress=task.progress,
        is_group=False,
        type=task.type,
        color=task.color,
        requires_act=task.requires_act,
        act_signed=task.act_signed,
        row_order=(float(task.row_order) + next_order) / 2,
    )
    db.add(second_task)
    await db.flush()

    outgoing_deps = list(await db.scalars(
        select(TaskDependency)
        .where(TaskDependency.depends_on == task.id)
    ))
    for dep in outgoing_deps:
        await db.delete(dep)
        db.add(TaskDependency(task_id=dep.task_id, depends_on=second_task.id))

    db.add(TaskDependency(task_id=second_task.id, depends_on=task.id))

    task.name = f"{original_name} (этап 1)"
    task.working_days = first_days
    task.workers_count = original_workers
    db.add(task)

    db.add(TaskHistory(
        id=str(uuid4()),
        task_id=task.id,
        project_id=task.project_id,
        user_id=actor_id,
        action="split",
        old_data={
            "name": original_name,
            "working_days": first_days + second_days,
            "workers_count": original_workers,
        },
        new_data={
            "first_task_id": task.id,
            "first_name": task.name,
            "first_working_days": first_days,
            "first_workers_count": task.workers_count,
            "second_task_id": second_task.id,
            "second_name": second_task.name,
            "second_start_date": str(second_task.start_date),
            "second_working_days": second_task.working_days,
            "second_workers_count": second_task.workers_count,
        },
    ))

    affected = await resolve_project_dates(task.project_id, db)
    return task, second_task, affected


async def _reindex_project_tasks(project_id: str, db: AsyncSession) -> None:
    await db.execute(text("""
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY project_id ORDER BY row_order, created_at
                   ) * 1000 AS new_order
              FROM gantt_tasks
             WHERE project_id = :pid AND deleted_at IS NULL
        )
        UPDATE gantt_tasks t SET row_order = r.new_order
          FROM ranked r WHERE t.id = r.id
    """), {"pid": project_id})


async def _get_next_row_order(task: GanttTask, db: AsyncSession) -> float:
    next_task = await db.scalar(
        select(GanttTask)
        .where(GanttTask.project_id == task.project_id)
        .where(GanttTask.deleted_at == None)
        .where(GanttTask.row_order > task.row_order)
        .order_by(GanttTask.row_order)
        .limit(1)
    )
    if next_task:
        return float(next_task.row_order)
    return float(task.row_order) + 1000.0


async def _refresh_is_group(parent_id: str, db: AsyncSession) -> None:
    """Пересчитывает is_group после изменений в дереве."""
    count = await db.scalar(
        select(func.count()).select_from(GanttTask)
        .where(GanttTask.parent_id  == parent_id)
        .where(GanttTask.deleted_at == None)
    )
    parent = await db.get(GanttTask, parent_id)
    if parent:
        parent.is_group = (count or 0) > 0
        db.add(parent)


# ── Мягкое удаление ──────────────────────────────────────────────────────────

async def soft_delete_task(
    task: GanttTask,
    actor_id: str,
    db: AsyncSession,
) -> list[str]:
    """
    Помечает задачу и всех потомков как deleted_at=now.
    Физически строки не удаляются — история и аудит сохраняются.
    Возвращает список ID удалённых задач.
    """
    deleted_ids: list[str] = []

    async def _delete(t: GanttTask) -> None:
        t.deleted_at = datetime.utcnow()
        db.add(t)
        db.add(TaskHistory(
            id         = str(uuid4()),
            task_id    = t.id,
            project_id = t.project_id,
            user_id    = actor_id,
            action     = "deleted",
            old_data   = {
                "name":         t.name,
                "start_date":   str(t.start_date),
                "working_days": t.working_days,
                "progress":     t.progress,
            },
        ))
        deleted_ids.append(t.id)

        children = await db.scalars(
            select(GanttTask)
            .where(GanttTask.parent_id  == t.id)
            .where(GanttTask.deleted_at == None)
        )
        for child in children:
            await _delete(child)

    await _delete(task)

    if task.parent_id:
        await _refresh_is_group(task.parent_id, db)

    return deleted_ids
