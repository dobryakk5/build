import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


def _full_url(path: str, token: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{settings.APP_BASE_URL.rstrip('/')}{path}{separator}token={token}"


def _smtp_sender_email() -> str:
    _, email = parseaddr(settings.EMAIL_FROM)
    return email or settings.EMAIL_FROM


def _build_message(*, to_email: str, subject: str, html: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.EMAIL_FROM
    message["To"] = to_email
    message.set_content(
        "Ваш почтовый клиент не поддерживает HTML-версию письма. "
        "Откройте письмо в современном почтовом клиенте."
    )
    message.add_alternative(html, subtype="html")
    return message


def resolve_email_provider() -> str:
    if settings.EMAIL_PROVIDER == "resend" and settings.RESEND_API_KEY:
        return "resend"
    if settings.EMAIL_PROVIDER == "smtp":
        return "smtp"
    return "log"


def _send_via_smtp(*, to_email: str, subject: str, html: str) -> None:
    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP_HOST is not configured")

    message = _build_message(to_email=to_email, subject=subject, html=html)
    timeout = settings.SMTP_TIMEOUT_SECONDS

    if settings.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout) as server:
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(message, from_addr=_smtp_sender_email(), to_addrs=[to_email])
        return

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout) as server:
        server.ehlo()
        if settings.SMTP_USE_TLS:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message, from_addr=_smtp_sender_email(), to_addrs=[to_email])


async def _send_email(*, to_email: str, subject: str, html: str) -> str:
    provider = resolve_email_provider()

    if provider == "resend":
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                },
            )
            response.raise_for_status()
        logger.info("email_sent", extra={"provider": "resend", "to": to_email, "subject": subject})
        return "resend"

    if provider == "smtp":
        await asyncio.to_thread(
            _send_via_smtp,
            to_email=to_email,
            subject=subject,
            html=html,
        )
        logger.info("email_sent", extra={"provider": "smtp", "to": to_email, "subject": subject})
        return "smtp"

    logger.info("email_dry_run", extra={"provider": "log", "to": to_email, "subject": subject})
    logger.debug("email_dry_run_body", extra={"provider": "log", "to": to_email, "subject": subject, "html": html})
    return "log"


async def send_verification_email(*, to_email: str, token: str) -> str:
    verify_url = _full_url("/auth/verify-email", token)
    return await _send_email(
        to_email=to_email,
        subject="Подтвердите email",
        html=(
            "<p>Подтвердите email для входа в СтройКонтроль.</p>"
            f"<p><a href=\"{verify_url}\">Подтвердить email</a></p>"
            f"<p>Если кнопка не работает, откройте ссылку: {verify_url}</p>"
        ),
    )


async def send_password_reset_email(*, to_email: str, token: str) -> str:
    reset_url = _full_url("/auth/reset-password", token)
    return await _send_email(
        to_email=to_email,
        subject="Сброс пароля",
        html=(
            "<p>Получен запрос на сброс пароля в СтройКонтроль.</p>"
            f"<p><a href=\"{reset_url}\">Сбросить пароль</a></p>"
            f"<p>Если кнопка не работает, откройте ссылку: {reset_url}</p>"
        ),
    )


def _make_respond_url(base_url: str, report_id: str, token: str, status: str) -> str:
    return (
        f"{base_url.rstrip('/')}/api/foreman-reports/{report_id}/respond"
        f"?token={token}&status={status}"
    )


async def send_foreman_task_email(
    *,
    to_email: str,
    foreman_name: str,
    project_name: str,
    task_name: str,
    report_date: str,
    report_id: str,
    token: str,
) -> str:
    base_url = settings.APP_BASE_URL
    url_planned = _make_respond_url(base_url, report_id, token, "done_as_planned")
    url_not_planned = _make_respond_url(base_url, report_id, token, "done_not_as_planned")
    url_not_done = _make_respond_url(base_url, report_id, token, "not_done")

    btn = (
        "display:inline-block;padding:12px 24px;border-radius:6px;"
        "font-size:14px;font-weight:600;text-decoration:none;color:#ffffff;"
    )
    html = f"""
<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;">
    <div style="background:#1e3a5f;padding:24px 32px;">
      <h2 style="margin:0;color:#ffffff;font-size:18px;">СтройКонтроль - Отчет за {report_date}</h2>
    </div>
    <div style="padding:28px 32px;">
      <p style="margin:0 0 8px;color:#555;font-size:14px;">Здравствуйте, <strong>{foreman_name}</strong>!</p>
      <p style="margin:0 0 20px;color:#555;font-size:14px;">
        Проект: <strong>{project_name}</strong>
      </p>

      <div style="background:#f8fafc;border-left:4px solid #3b82f6;
                  border-radius:4px;padding:16px 20px;margin-bottom:24px;">
        <p style="margin:0 0 4px;font-size:11px;color:#9ca3af;text-transform:uppercase;
                  letter-spacing:.06em;">Задача на сегодня</p>
        <p style="margin:0;font-size:16px;font-weight:600;color:#1e293b;">{task_name}</p>
      </div>

      <p style="margin:0 0 16px;color:#374151;font-size:14px;font-weight:600;">
        Как выполнена задача?
      </p>

      <table cellpadding="0" cellspacing="0" style="width:100%;">
        <tr>
          <td style="padding-bottom:10px;">
            <a href="{url_planned}"
               style="{btn}background:#16a34a;display:block;text-align:center;">
              Выполнил по плану
            </a>
          </td>
        </tr>
        <tr>
          <td style="padding-bottom:10px;">
            <a href="{url_not_planned}"
               style="{btn}background:#d97706;display:block;text-align:center;">
              Выполнил не по плану
            </a>
          </td>
        </tr>
        <tr>
          <td>
            <a href="{url_not_done}"
               style="{btn}background:#dc2626;display:block;text-align:center;">
              Не выполнил
            </a>
          </td>
        </tr>
      </table>

      <p style="margin:24px 0 0;font-size:12px;color:#9ca3af;">
        Это автоматическое письмо от системы СтройКонтроль.
        Нажмите одну кнопку - ответ сразу запишется в журнал проекта.
      </p>
    </div>
  </div>
</body>
</html>
"""

    return await _send_email(
        to_email=to_email,
        subject=f"[{project_name}] Отчет прораба за {report_date}: {task_name}",
        html=html,
    )
