from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "construction",
    broker  = settings.CELERY_BROKER_URL,
    backend = settings.CELERY_RESULT_BACKEND,
    include = ["app.tasks.report_tasks", "app.tasks.foreman_email_tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=60 * 60 * 24,
    timezone="Europe/Moscow",
    enable_utc=True,
)

celery_app.conf.beat_schedule = {
    # 22:00 — напоминание прорабам заполнить отчёт
    "remind-foremen-daily": {
        "task":     "app.tasks.report_tasks.remind_foremen",
        "schedule": crontab(hour=22, minute=0),
    },
    # 07:00 — проверка отчётов за вчера, создание эскалаций, обновление дашборда
    "morning-summary": {
        "task":     "app.tasks.report_tasks.morning_summary",
        "schedule": crontab(hour=7, minute=0),
    },
    # Каждый час — эскалация открытых проблем старше 48ч
    "escalate-overdue": {
        "task":     "app.tasks.report_tasks.escalate_overdue",
        "schedule": crontab(minute=0),
    },
    "foreman-daily-emails": {
        "task":     "app.tasks.foreman_email_tasks.send_foreman_daily_emails",
        "schedule": crontab(hour=18, minute=0),
    },
}
