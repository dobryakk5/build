from pathlib import Path
import sys
import logging
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_celery_app_has_acks_late():
    from app.tasks.celery_app import celery_app

    assert celery_app.conf.task_acks_late is True


def test_celery_app_has_reject_on_worker_lost():
    from app.tasks.celery_app import celery_app

    assert celery_app.conf.task_reject_on_worker_lost is True


def test_celery_app_has_result_expires():
    from app.tasks.celery_app import celery_app

    assert celery_app.conf.result_expires is not None
    assert celery_app.conf.result_expires > 0


def test_all_tasks_have_retry_config():
    from app.tasks.foreman_email_tasks import send_foreman_daily_emails
    from app.tasks.report_tasks import remind_foremen, morning_summary, escalate_overdue

    for task in (remind_foremen, morning_summary, escalate_overdue, send_foreman_daily_emails):
        assert task.max_retries is not None and task.max_retries > 0
        assert task.default_retry_delay is not None and task.default_retry_delay > 0


def test_celery_app_includes_foreman_email_schedule():
    from app.tasks.celery_app import celery_app

    assert "app.tasks.foreman_email_tasks" in celery_app.conf.include
    assert "foreman-daily-emails" in celery_app.conf.beat_schedule


def test_remind_foremen_retries_on_error(caplog):
    from app.tasks.report_tasks import remind_foremen

    with patch("app.tasks.report_tasks.run_async", side_effect=ConnectionError("DB down")):
        with caplog.at_level(logging.ERROR, logger="app.tasks.report_tasks"):
            remind_foremen.apply()

    attempt_msgs = [r for r in caplog.records if "attempt" in r.message.lower() or "failed" in r.message.lower()]
    assert len(attempt_msgs) >= 2


def test_task_does_not_raise_after_max_retries():
    from app.tasks.report_tasks import remind_foremen

    with patch("app.tasks.report_tasks.run_async", side_effect=RuntimeError("fatal")):
        result = remind_foremen.apply()

    assert result is not None


def test_success_path_has_no_error_logs(caplog):
    from app.tasks.report_tasks import morning_summary

    with patch("app.tasks.report_tasks.run_async", return_value=None):
        with caplog.at_level(logging.ERROR, logger="app.tasks.report_tasks"):
            morning_summary.apply()

    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
