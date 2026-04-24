from pathlib import Path
import logging
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services import email_service


@pytest.mark.asyncio
async def test_send_email_dry_run_logs_only_metadata_at_info(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")

    caplog.set_level(logging.DEBUG, logger=email_service.logger.name)

    provider = await email_service._send_email(
        to_email="user@example.com",
        subject="Verify",
        html="<a href='https://example.com?token=secret-token'>verify</a>",
    )

    assert provider == "log"

    info_record = next(record for record in caplog.records if record.msg == "email_dry_run")
    debug_record = next(record for record in caplog.records if record.msg == "email_dry_run_body")

    assert info_record.provider == "log"
    assert info_record.to == "user@example.com"
    assert info_record.subject == "Verify"
    assert not hasattr(info_record, "html")
    assert debug_record.html == "<a href='https://example.com?token=secret-token'>verify</a>"


@pytest.mark.asyncio
async def test_send_email_logs_success_for_smtp(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")

    called: dict[str, object] = {}

    async def fake_to_thread(func, **kwargs):
        called["func"] = func
        called["kwargs"] = kwargs

    monkeypatch.setattr(email_service.asyncio, "to_thread", fake_to_thread)
    caplog.set_level(logging.INFO, logger=email_service.logger.name)

    provider = await email_service._send_email(
        to_email="user@example.com",
        subject="Verify",
        html="<p>Hello</p>",
    )

    assert provider == "smtp"
    assert called["func"] is email_service._send_via_smtp
    assert called["kwargs"] == {
        "to_email": "user@example.com",
        "subject": "Verify",
        "html": "<p>Hello</p>",
    }

    record = next(record for record in caplog.records if record.msg == "email_sent")
    assert record.provider == "smtp"
    assert record.to == "user@example.com"
    assert record.subject == "Verify"


@pytest.mark.asyncio
async def test_send_email_logs_success_for_resend(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "test-key")

    calls: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            calls["raise_for_status"] = True

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            calls["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
            calls["url"] = url
            calls["headers"] = headers
            calls["json"] = json
            return FakeResponse()

    monkeypatch.setattr(email_service.httpx, "AsyncClient", FakeAsyncClient)
    caplog.set_level(logging.INFO, logger=email_service.logger.name)

    provider = await email_service._send_email(
        to_email="user@example.com",
        subject="Verify",
        html="<p>Hello</p>",
    )

    assert provider == "resend"
    assert calls["url"] == "https://api.resend.com/emails"
    assert calls["headers"]["Authorization"] == "Bearer test-key"
    assert calls["json"]["to"] == ["user@example.com"]
    assert calls["raise_for_status"] is True

    record = next(record for record in caplog.records if record.msg == "email_sent")
    assert record.provider == "resend"
    assert record.to == "user@example.com"
    assert record.subject == "Verify"


@pytest.mark.asyncio
async def test_send_foreman_task_email_builds_callback_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://example.com/app")

    captured: dict[str, str] = {}

    async def fake_send_email(*, to_email: str, subject: str, html: str) -> str:
        captured["to_email"] = to_email
        captured["subject"] = subject
        captured["html"] = html
        return "log"

    monkeypatch.setattr(email_service, "_send_email", fake_send_email)

    provider = await email_service.send_foreman_task_email(
        to_email="foreman@example.com",
        foreman_name="Иван",
        project_name="ЖК Север",
        task_name="Монтаж перекрытий",
        report_date="2026-04-24",
        report_id="report-123",
        token="token-xyz",
    )

    assert provider == "log"
    assert captured["to_email"] == "foreman@example.com"
    assert "[ЖК Север] Отчет прораба за 2026-04-24: Монтаж перекрытий" == captured["subject"]
    assert "/api/foreman-reports/report-123/respond?token=token-xyz&status=done_as_planned" in captured["html"]
    assert "/api/foreman-reports/report-123/respond?token=token-xyz&status=done_not_as_planned" in captured["html"]
    assert "/api/foreman-reports/report-123/respond?token=token-xyz&status=not_done" in captured["html"]
