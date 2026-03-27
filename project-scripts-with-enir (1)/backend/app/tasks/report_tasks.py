"""
Фоновые задачи для работы с отчётами и эскалациями.
Запускаются Celery Beat по расписанию из celery_app.py.
"""
import asyncio
from datetime import date, datetime, timedelta
from uuid import uuid4

from app.tasks.celery_app import celery_app


def run_async(coro):
    """Запускает async корутину из синхронного Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── 22:00 — напоминания прорабам ──────────────────────────────────────────────

@celery_app.task(name="app.tasks.report_tasks.remind_foremen")
def remind_foremen():
    """Пушит уведомление прорабам у которых нет отчёта за сегодня."""
    run_async(_remind_foremen_async())


async def _remind_foremen_async():
    from sqlalchemy import select
    from app.core.database import get_db_context
    from app.models import Project, ProjectMember, DailyReport, Notification

    today = date.today()

    async with get_db_context() as db:
        projects = await db.scalars(
            select(Project)
            .where(Project.status     == "active")
            .where(Project.deleted_at == None)
        )
        for project in projects:
            foremen = await db.scalars(
                select(ProjectMember)
                .where(ProjectMember.project_id == project.id)
                .where(ProjectMember.role       == "foreman")
            )
            for foreman in foremen:
                submitted = await db.scalar(
                    select(DailyReport)
                    .where(DailyReport.project_id  == project.id)
                    .where(DailyReport.author_id   == foreman.user_id)
                    .where(DailyReport.report_date == today)
                    .where(DailyReport.status      == "submitted")
                )
                if submitted:
                    continue
                db.add(Notification(
                    id          = str(uuid4()),
                    user_id     = foreman.user_id,
                    type        = "report_reminder",
                    title       = "Заполни отчёт за сегодня",
                    body        = f"Проект: {project.name}. Срок: до 23:59.",
                    entity_type = "project",
                    entity_id   = project.id,
                ))
        await db.commit()


# ── 07:00 — проверка вчерашних отчётов ───────────────────────────────────────

@celery_app.task(name="app.tasks.report_tasks.morning_summary")
def morning_summary():
    """Создаёт эскалации за пропущенные отчёты, уведомляет PM, обновляет дашборд."""
    run_async(_morning_summary_async())


async def _morning_summary_async():
    from sqlalchemy import select
    from app.core.database import get_db_context
    from app.models import Project, ProjectMember, DailyReport, Escalation, Notification, User

    yesterday = date.today() - timedelta(days=1)

    async with get_db_context() as db:
        projects = await db.scalars(
            select(Project)
            .where(Project.status     == "active")
            .where(Project.deleted_at == None)
        )
        for project in projects:
            foremen = await db.scalars(
                select(ProjectMember)
                .where(ProjectMember.project_id == project.id)
                .where(ProjectMember.role       == "foreman")
            )
            missing_names = []
            for foreman in foremen:
                submitted = await db.scalar(
                    select(DailyReport)
                    .where(DailyReport.project_id  == project.id)
                    .where(DailyReport.author_id   == foreman.user_id)
                    .where(DailyReport.report_date == yesterday)
                    .where(DailyReport.status      == "submitted")
                )
                if submitted:
                    continue

                user = await db.get(User, foreman.user_id)
                if user:
                    missing_names.append(user.name)

                db.add(Escalation(
                    id          = str(uuid4()),
                    project_id  = project.id,
                    type        = "no_report",
                    meta        = {"foreman_id": foreman.user_id, "report_date": str(yesterday)},
                    status      = "open",
                    detected_at = datetime.utcnow(),
                ))

            if missing_names:
                pm = await db.scalar(
                    select(ProjectMember)
                    .where(ProjectMember.project_id == project.id)
                    .where(ProjectMember.role.in_(["pm", "owner"]))
                )
                if pm:
                    db.add(Notification(
                        id          = str(uuid4()),
                        user_id     = pm.user_id,
                        type        = "missing_reports",
                        title       = f"Нет отчётов за {yesterday}",
                        body        = f"Не сдали: {', '.join(missing_names)}",
                        entity_type = "project",
                        entity_id   = project.id,
                    ))

            await _update_dashboard_status(project.id, db)

        await db.commit()


# ── Каждый час — эскалация 48ч ───────────────────────────────────────────────

@celery_app.task(name="app.tasks.report_tasks.escalate_overdue")
def escalate_overdue():
    """Поднимает эскалации старше 48ч до owner и уведомляет директора."""
    run_async(_escalate_overdue_async())


async def _escalate_overdue_async():
    from sqlalchemy import select
    from app.core.database import get_db_context
    from app.models import Escalation, ProjectMember, Notification

    threshold = datetime.utcnow() - timedelta(hours=48)

    async with get_db_context() as db:
        old_open = await db.scalars(
            select(Escalation)
            .where(Escalation.status      == "open")
            .where(Escalation.detected_at <= threshold)
        )
        for esc in old_open:
            esc.status       = "escalated"
            esc.escalated_at = datetime.utcnow()
            db.add(esc)

            owner = await db.scalar(
                select(ProjectMember)
                .where(ProjectMember.project_id == esc.project_id)
                .where(ProjectMember.role       == "owner")
            )
            if owner:
                db.add(Notification(
                    id          = str(uuid4()),
                    user_id     = owner.user_id,
                    type        = "escalation",
                    title       = "⚠️ Требуется вмешательство",
                    body        = f"Проблема без решения более 48 часов (тип: {esc.type})",
                    entity_type = "escalation",
                    entity_id   = esc.id,
                ))

        await db.commit()


# ── Вспомогательная функция ───────────────────────────────────────────────────

async def _update_dashboard_status(project_id: str, db) -> None:
    """
    Пересчитывает dashboard_status проекта: green / yellow / red.
    Вызывается из morning_summary каждое утро.
    """
    from sqlalchemy import select, func
    from app.models import Escalation, Project

    escalated = await db.scalar(
        select(func.count()).select_from(Escalation)
        .where(Escalation.project_id == project_id)
        .where(Escalation.status     == "escalated")
    ) or 0

    open_escs = await db.scalar(
        select(func.count()).select_from(Escalation)
        .where(Escalation.project_id == project_id)
        .where(Escalation.status     == "open")
    ) or 0

    if escalated > 0:
        status = "red"
    elif open_escs > 0:
        status = "yellow"
    else:
        status = "green"

    project = await db.get(Project, project_id)
    if project:
        project.dashboard_status = status
        db.add(project)
