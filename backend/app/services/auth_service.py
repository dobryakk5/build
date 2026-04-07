import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models import (
    AuthAuditEvent,
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    User,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def get_request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def get_request_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _cookie_secure() -> bool:
    return settings.AUTH_COOKIE_SECURE or settings.APP_BASE_URL.startswith("https://")


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    cookie_kwargs = {
        "httponly": True,
        "secure": _cookie_secure(),
        "domain": settings.AUTH_COOKIE_DOMAIN,
        "path": "/",
    }
    response.set_cookie(
        key=settings.AUTH_ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        **cookie_kwargs,
    )
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        samesite="lax",
        **cookie_kwargs,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        settings.AUTH_ACCESS_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )
    response.delete_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )


async def create_session(db: AsyncSession, *, user: User, request: Request) -> tuple[AuthSession, str, str]:
    raw_refresh_token = generate_token()
    now = utcnow()
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_token(raw_refresh_token),
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        last_used_at=now,
        ip=get_request_ip(request),
        user_agent=get_request_user_agent(request),
    )
    db.add(session)
    await db.flush()
    access_token = create_access_token(user.id)
    return session, raw_refresh_token, access_token


async def get_active_session_by_refresh_token(db: AsyncSession, refresh_token: str | None) -> AuthSession | None:
    if not refresh_token:
        return None

    session = await db.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(refresh_token))
    )
    if not session:
        return None
    now = utcnow()
    if session.revoked_at or session.expires_at <= now:
        return None
    return session


async def rotate_session(
    db: AsyncSession,
    *,
    current_session: AuthSession,
    request: Request,
) -> tuple[AuthSession, str, str]:
    now = utcnow()
    current_session.revoked_at = now
    user = await db.get(User, current_session.user_id)
    if user is None:
        raise ValueError("user not found")
    return await create_session(db, user=user, request=request)


async def revoke_session(db: AsyncSession, session: AuthSession | None) -> None:
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()


async def revoke_all_user_sessions(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id)
        .where(AuthSession.revoked_at == None)
        .values(revoked_at=utcnow())
    )


async def issue_email_verification_token(db: AsyncSession, *, user_id: str) -> str:
    now = utcnow()
    await db.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user_id)
        .where(EmailVerificationToken.used_at == None)
        .values(used_at=now)
    )
    raw_token = generate_token()
    db.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
        )
    )
    await db.flush()
    return raw_token


async def issue_password_reset_token(db: AsyncSession, *, user_id: str) -> str:
    now = utcnow()
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id)
        .where(PasswordResetToken.used_at == None)
        .values(used_at=now)
    )
    raw_token = generate_token()
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(hours=settings.PASSWORD_RESET_EXPIRE_HOURS),
        )
    )
    await db.flush()
    return raw_token


async def consume_email_verification_token(db: AsyncSession, *, token: str) -> EmailVerificationToken | None:
    now = utcnow()
    verification = await db.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == hash_token(token))
    )
    if not verification or verification.used_at or verification.expires_at <= now:
        return None
    verification.used_at = now
    return verification


async def consume_password_reset_token(db: AsyncSession, *, token: str) -> PasswordResetToken | None:
    now = utcnow()
    reset_token = await db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token))
    )
    if not reset_token or reset_token.used_at or reset_token.expires_at <= now:
        return None
    reset_token.used_at = now
    return reset_token


async def log_auth_event(
    db: AsyncSession,
    *,
    event_type: str,
    request: Request,
    user: User | None = None,
    email: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuthAuditEvent(
            user_id=user.id if user else None,
            event_type=event_type,
            email=email or (user.email if user else None),
            ip=get_request_ip(request),
            user_agent=get_request_user_agent(request),
            details=details or {},
        )
    )
