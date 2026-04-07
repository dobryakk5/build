import logging

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


def _full_url(path: str, token: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{settings.APP_BASE_URL.rstrip('/')}{path}{separator}token={token}"


async def _send_email(*, to_email: str, subject: str, html: str) -> None:
    if settings.EMAIL_PROVIDER == "resend" and settings.RESEND_API_KEY:
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
        return

    logger.info("Email provider fallback", extra={"to_email": to_email, "subject": subject, "html": html})


async def send_verification_email(*, to_email: str, token: str) -> None:
    verify_url = _full_url("/auth/verify-email", token)
    await _send_email(
        to_email=to_email,
        subject="Подтвердите email",
        html=(
            "<p>Подтвердите email для входа в СтройКонтроль.</p>"
            f"<p><a href=\"{verify_url}\">Подтвердить email</a></p>"
            f"<p>Если кнопка не работает, откройте ссылку: {verify_url}</p>"
        ),
    )


async def send_password_reset_email(*, to_email: str, token: str) -> None:
    reset_url = _full_url("/auth/reset-password", token)
    await _send_email(
        to_email=to_email,
        subject="Сброс пароля",
        html=(
            "<p>Получен запрос на сброс пароля в СтройКонтроль.</p>"
            f"<p><a href=\"{reset_url}\">Сбросить пароль</a></p>"
            f"<p>Если кнопка не работает, откройте ссылку: {reset_url}</p>"
        ),
    )
