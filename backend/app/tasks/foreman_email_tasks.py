import asyncio
import hashlib
import hmac
import logging
import time
from datetime import date, datetime, timezone
from uuid import uuid4

from celery.exceptions import MaxRetriesExceededError

from app.core.config import settings
from app.tasks.celery_app import celery_app


logger = logging.getLogger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_report_token(report_id: str) -> str:
    ts = str(int(time.time()))
    payload = f"{report_id}:{ts}"
    sig = hmac.new(
        settings.SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{sig}"


def verify_report_token(token: str, report_id: str) -> bool:
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        rid, ts_str, sig = parts
        if rid != report_id:
            return False
        age = int(time.time()) - int(ts_str)
        if age > 48 * 3600:
            return False
        payload = f"{rid}:{ts_str}"
        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


@celery_app.task(
    name="app.tasks.foreman_email_tasks.send_foreman_daily_emails",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def send_foreman_daily_emails(self):
    coro = _send_foreman_daily_emails_async()
    try:
        run_async(coro)
    except Exception as exc:
        logger.exception(
            "send_foreman_daily_emails failed (attempt %d): %s",
            self.request.retries + 1,
            exc,
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("send_foreman_daily_emails: all retry attempts exhausted")


async def _send_foreman_daily_emails_async():
    from sqlalchemy import select

    from app.core.database import get_db_context
    from app.models import GanttTask, Project, ProjectMember, User
    from app.models.foreman_task_report import ForemanTaskReport
    from app.services.email_service import send_foreman_task_email

    today = date.today()
    today_str = today.isoformat()

    async with get_db_context() as db:
        projects = list(
            await db.scalars(
                select(Project)
                .where(Project.status == "active")
                .where(Project.deleted_at.is_(None))
            )
        )

        for project in projects:
            foremen = list(
                await db.scalars(
                    select(ProjectMember)
                    .where(ProjectMember.project_id == project.id)
                    .where(ProjectMember.role == "foreman")
                )
            )
            if not foremen:
                continue

            current_task = await db.scalar(
                select(GanttTask)
                .where(GanttTask.project_id == project.id)
                .where(GanttTask.deleted_at.is_(None))
                .where(GanttTask.is_group.is_(False))
                .where(GanttTask.progress < 100)
                .where(GanttTask.start_date <= today)
                .order_by(GanttTask.row_order.asc())
                .limit(1)
            )
            if not current_task:
                logger.info(
                    "foreman_email: no active task in project %s (%s), skipping",
                    project.name,
                    project.id,
                )
                continue

            for member in foremen:
                foreman_user = await db.get(User, member.user_id)
                if not foreman_user or not foreman_user.email:
                    logger.warning(
                        "foreman_email: foreman user_id=%s not found or has no email, skipping",
                        member.user_id,
                    )
                    continue

                existing = await db.scalar(
                    select(ForemanTaskReport)
                    .where(ForemanTaskReport.project_id == project.id)
                    .where(ForemanTaskReport.task_id == current_task.id)
                    .where(ForemanTaskReport.foreman_id == foreman_user.id)
                    .where(ForemanTaskReport.report_date == today)
                )
                if existing:
                    logger.info(
                        "foreman_email: duplicate skipped project=%s task=%s foreman=%s",
                        project.id,
                        current_task.id,
                        foreman_user.id,
                    )
                    continue

                report_id = str(uuid4())
                token = _make_report_token(report_id)
                report = ForemanTaskReport(
                    id=report_id,
                    project_id=project.id,
                    task_id=current_task.id,
                    foreman_id=foreman_user.id,
                    report_date=today,
                    token=token,
                    status="pending",
                )
                db.add(report)
                await db.flush()

                try:
                    await send_foreman_task_email(
                        to_email=foreman_user.email,
                        foreman_name=foreman_user.name,
                        project_name=project.name,
                        task_name=current_task.name,
                        report_date=today_str,
                        report_id=report_id,
                        token=token,
                    )
                    report.email_sent_at = datetime.now(timezone.utc)
                    logger.info(
                        "foreman_email: sent to %s | task='%s' | project='%s'",
                        foreman_user.email,
                        current_task.name,
                        project.name,
                    )
                except Exception as send_exc:
                    logger.error(
                        "foreman_email: SMTP/API error for %s: %s",
                        foreman_user.email,
                        send_exc,
                    )
                    await db.delete(report)

        await db.commit()
