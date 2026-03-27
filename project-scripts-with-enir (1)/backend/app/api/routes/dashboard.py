"""
GET /dashboard — главный экран руководителя.
Возвращает все проекты организации со статусами (домики зелёный/жёлтый/красный).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps  import get_current_user, get_db
from app.models    import Project, ProjectMember, User, Estimate, GanttTask, Escalation

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard(
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """
    Список всех проектов пользователя с ключевыми метриками для дашборда.
    dashboard_status обновляется Celery каждое утро.
    """
    # Проекты пользователя
    member_rows = await db.scalars(
        select(ProjectMember).where(ProjectMember.user_id == current_user.id)
    )
    members     = list(member_rows)
    project_ids = [m.project_id for m in members]
    role_map    = {m.project_id: m.role for m in members}

    if not project_ids:
        return {"projects": [], "summary": {"total": 0, "green": 0, "yellow": 0, "red": 0}}

    projects = await db.scalars(
        select(Project)
        .where(Project.id.in_(project_ids))
        .where(Project.deleted_at == None)
        .order_by(Project.created_at.desc())
    )

    result     = []
    counts     = {"green": 0, "yellow": 0, "red": 0}
    total_budget = 0.0
    total_spent  = 0.0

    for p in projects:
        s = p.dashboard_status or "green"
        if s in counts:
            counts[s] += 1

        # Бюджет из сметы
        budget = await db.scalar(
            select(func.sum(Estimate.total_price))
            .where(Estimate.project_id == p.id)
            .where(Estimate.deleted_at == None)
        ) or 0.0
        total_budget += float(budget)

        # Количество задач
        tasks_total = await db.scalar(
            select(func.count()).select_from(GanttTask)
            .where(GanttTask.project_id == p.id)
            .where(GanttTask.deleted_at == None)
            .where(GanttTask.is_group   == False)
        ) or 0

        # Завершённые задачи
        tasks_done = await db.scalar(
            select(func.count()).select_from(GanttTask)
            .where(GanttTask.project_id == p.id)
            .where(GanttTask.deleted_at == None)
            .where(GanttTask.is_group   == False)
            .where(GanttTask.progress   == 100)
        ) or 0

        progress = round(tasks_done / tasks_total * 100) if tasks_total else 0

        # Открытые эскалации
        escalations = await db.scalar(
            select(func.count()).select_from(Escalation)
            .where(Escalation.project_id == p.id)
            .where(Escalation.status.in_(["open", "escalated"]))
        ) or 0

        result.append({
            "id":               p.id,
            "name":             p.name,
            "address":          p.address,
            "status":           p.status,
            "dashboard_status": s,
            "color":            p.color,
            "start_date":       str(p.start_date) if p.start_date else None,
            "end_date":         str(p.end_date)   if p.end_date   else None,
            "my_role":          role_map.get(p.id),
            "progress":         progress,
            "tasks_total":      tasks_total,
            "tasks_done":       tasks_done,
            "budget":           float(budget),
            "open_escalations": escalations,
        })

    return {
        "projects": result,
        "summary": {
            "total":        len(result),
            "green":        counts["green"],
            "yellow":       counts["yellow"],
            "red":          counts["red"],
            "total_budget": total_budget,
        },
    }
