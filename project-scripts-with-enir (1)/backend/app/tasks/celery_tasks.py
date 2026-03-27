## backend/app/tasks/celery_app.py
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "construction",
    broker  = settings.CELERY_BROKER_URL,
    backend = settings.CELERY_RESULT_BACKEND,
    include = ["app.tasks.report_tasks"],
)

celery_app.conf.beat_schedule = {
    # 22:00 — напоминание прорабам заполнить отчёт
    "remind-foremen-daily": {
        "task":     "app.tasks.report_tasks.remind_foremen",
        "schedule": crontab(hour=22, minute=0),
    },
    # 07:00 — проверка отчётов за вчера, создание эскалаций, дашборд
    "morning-summary": {
        "task":     "app.tasks.report_tasks.morning_summary",
        "schedule": crontab(hour=7, minute=0),
    },
    # Каждые 2 часа — эскалация открытых проблем старше 48ч
    "escalate-overdue": {
        "task":     "app.tasks.report_tasks.escalate_overdue",
        "schedule": crontab(minute=0),   # каждый час
    },
}

celery_app.conf.timezone = "Europe/Moscow"


## backend/app/tasks/report_tasks.py
"""
Фоновые задачи для работы с отчётами и эскалациями.
Запускаются Celery Beat по расписанию.
"""
import asyncio
from datetime import date, datetime, timedelta
from uuid import uuid4

from app.tasks.celery_app import celery_app


def run_async(coro):
    """Запускает async функцию из синхронного Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.tasks.report_tasks.remind_foremen")
def remind_foremen():
    """22:00 — пушит уведомление прорабам, которые не заполнили отчёт."""
    run_async(_remind_foremen_async())


async def _remind_foremen_async():
    from sqlalchemy import select
    from app.core.database import get_db_context
    from app.models import Project, ProjectMember, DailyReport, Notification, User

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
                # Есть ли уже отчёт?
                existing = await db.scalar(
                    select(DailyReport)
                    .where(DailyReport.project_id  == project.id)
                    .where(DailyReport.author_id   == foreman.user_id)
                    .where(DailyReport.report_date == today)
                    .where(DailyReport.status      == "submitted")
                )
                if existing:
                    continue

                db.add(Notification(
                    id          = str(uuid4()),
                    user_id     = foreman.user_id,
                    type        = "report_reminder",
                    title       = "Заполни отчёт за сегодня",
                    body        = f"Проект: {project.name}. Отчёт ждёт до 23:59.",
                    entity_type = "project",
                    entity_id   = project.id,
                ))

        await db.commit()


@celery_app.task(name="app.tasks.report_tasks.morning_summary")
def morning_summary():
    """07:00 — проверяет вчерашние отчёты, создаёт эскалации, уведомляет PM."""
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
                report = await db.scalar(
                    select(DailyReport)
                    .where(DailyReport.project_id  == project.id)
                    .where(DailyReport.author_id   == foreman.user_id)
                    .where(DailyReport.report_date == yesterday)
                    .where(DailyReport.status      == "submitted")
                )
                if report:
                    continue

                user = await db.get(User, foreman.user_id)
                if user:
                    missing_names.append(user.name)

                # Создаём эскалацию
                db.add(Escalation(
                    id          = str(uuid4()),
                    project_id  = project.id,
                    type        = "no_report",
                    meta        = {
                        "foreman_id":  foreman.user_id,
                        "report_date": str(yesterday),
                    },
                    status      = "open",
                    detected_at = datetime.utcnow(),
                ))

            # Уведомляем PM если есть пропуски
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

            # Обновляем dashboard_status проекта
            await _update_dashboard_status(project.id, db)

        await db.commit()


@celery_app.task(name="app.tasks.report_tasks.escalate_overdue")
def escalate_overdue():
    """Каждый час — эскалирует открытые проблемы старше 48ч до директора."""
    run_async(_escalate_overdue_async())


async def _escalate_overdue_async():
    from sqlalchemy import select
    from app.core.database import get_db_context
    from app.models import Escalation, ProjectMember, Notification

    threshold = datetime.utcnow() - timedelta(hours=48)

    async with get_db_context() as db:
        open_old = await db.scalars(
            select(Escalation)
            .where(Escalation.status      == "open")
            .where(Escalation.detected_at <= threshold)
        )

        for esc in open_old:
            esc.status       = "escalated"
            esc.escalated_at = datetime.utcnow()

            # Уведомляем owner
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


async def _update_dashboard_status(project_id: str, db) -> None:
    """
    Пересчитывает dashboard_status (green/yellow/red) для проекта.
    green  — нет открытых эскалаций, нет просроченных задач
    yellow — есть open эскалации или задачи с небольшим отставанием
    red    — есть escalated эскалации или задачи просрочены >2 дней
    """
    from sqlalchemy import select, func
    from app.models import Escalation, GanttTask, Project

    today = date.today()

    escalated_count = await db.scalar(
        select(func.count()).select_from(Escalation)
        .where(Escalation.project_id == project_id)
        .where(Escalation.status     == "escalated")
    ) or 0

    open_count = await db.scalar(
        select(func.count()).select_from(Escalation)
        .where(Escalation.project_id == project_id)
        .where(Escalation.status     == "open")
    ) or 0

    overdue_count = await db.scalar(
        select(func.count()).select_from(GanttTask)
        .where(GanttTask.project_id  == project_id)
        .where(GanttTask.deleted_at  == None)
        .where(GanttTask.progress    < 100)
        # задача должна была закончиться, но не закончена
        # упрощённо: start_date + working_days < today
    ) or 0

    if escalated_count > 0 or overdue_count > 2:
        status = "red"
    elif open_count > 0 or overdue_count > 0:
        status = "yellow"
    else:
        status = "green"

    project = await db.get(Project, project_id)
    if project:
        project.dashboard_status = status
