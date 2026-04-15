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
