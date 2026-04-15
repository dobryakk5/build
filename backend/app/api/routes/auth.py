import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models import ProjectMember, User, Organization
from app.services.auth_service import (
    clear_auth_cookies,
    consume_email_verification_token,
    consume_password_reset_token,
    create_session,
    get_active_session_by_refresh_token,
    issue_email_verification_token,
    issue_password_reset_token,
    is_effectively_email_verified,
    log_auth_event,
    revoke_all_user_sessions,
    revoke_session,
    rotate_session,
    set_auth_cookies,
    utcnow,
)
from app.services.email_service import resolve_email_provider, send_password_reset_email, send_verification_email
from app.services.rate_limit_service import clear_rate_limit, enforce_rate_limit


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthUserResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    avatar_url: str | None = None
    role: str | None = None
    email_verified: bool
    is_superadmin: bool = False


class AuthResponse(BaseModel):
    user: AuthUserResponse
    email_verified: bool
    requires_email_verification: bool = False


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8)
    org_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MeResponse(AuthUserResponse):
    projects: list[dict]


class MeUpdate(BaseModel):
    name: str | None = None
    avatar_url: str | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=16)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16)
    new_password: str = Field(min_length=8)


def user_dict(user: User, role: str | None = None) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        avatar_url=user.avatar_url,
        role=role,
        email_verified=is_effectively_email_verified(user),
        is_superadmin=getattr(user, "is_superadmin", False),
    )


async def _log_email_delivery_event_safe(
    *,
    db: AsyncSession,
    request: Request,
    event_type: str,
    email_kind: str,
    provider: str,
    user: User | None = None,
    email: str | None = None,
    error: str | None = None,
) -> None:
    details = {"email_type": email_kind, "provider": provider}
    if error:
        details["error"] = error

    try:
        await log_auth_event(
            db,
            event_type=event_type,
            request=request,
            user=user,
            email=email,
            details=details,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to persist auth audit event %s for %s email", event_type, email_kind)


async def _send_verification_email_safe(*, email: str, token: str) -> tuple[bool, str, str | None]:
    provider = resolve_email_provider()
    try:
        provider = await send_verification_email(to_email=email, token=token)
        return True, provider, None
    except Exception as exc:
        logger.exception("Failed to send verification email to %s", email)
        return False, provider, str(exc)


async def _send_password_reset_email_safe(*, email: str, token: str) -> tuple[bool, str, str | None]:
    provider = resolve_email_provider()
    try:
        provider = await send_password_reset_email(to_email=email, token=token)
        return True, provider, None
    except Exception as exc:
        logger.exception("Failed to send password reset email to %s", email)
        return False, provider, str(exc)


def _login_failure_key(request: Request, email: str) -> str:
    ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    return f"auth:login-fail:{email.lower()}:{ip}"


def _scoped_ip_key(prefix: str, request: Request) -> str:
    ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    return f"{prefix}:{ip}"


def _email_ip_key(prefix: str, request: Request, email: str) -> str:
    ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    return f"{prefix}:{email.lower()}:{ip}"


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        _scoped_ip_key("auth:register", request),
        settings.RATE_LIMIT_REGISTER_ATTEMPTS,
        settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS,
        "Слишком много попыток регистрации. Повторите позже.",
    )

    if await db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(400, "Email уже зарегистрирован")

    org_name = body.org_name or f"{body.name}'s workspace"
    org = Organization(
        id=str(uuid4()),
        name=org_name,
        slug=org_name.lower().replace(" ", "-")[:90] + "-" + str(uuid4())[:8],
    )
    db.add(org)

    user = User(
        id=str(uuid4()),
        organization_id=org.id,
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        last_login_at=utcnow(),
    )
    db.add(user)
    await db.flush()

    _, raw_refresh_token, access_token = await create_session(db, user=user, request=request)
    verification_token = await issue_email_verification_token(db, user_id=user.id)
    await log_auth_event(db, event_type="register", request=request, user=user)
    await db.commit()

    set_auth_cookies(response, access_token=access_token, refresh_token=raw_refresh_token)
    sent, provider, error = await _send_verification_email_safe(email=user.email, token=verification_token)
    await _log_email_delivery_event_safe(
        db=db,
        request=request,
        event_type="email_sent" if sent else "email_failed",
        email_kind="verification",
        provider=provider,
        user=user,
        error=error,
    )

    payload = user_dict(user)
    return AuthResponse(
        user=payload,
        email_verified=payload.email_verified,
        requires_email_verification=True,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(User.email == body.email))
    failure_key = _login_failure_key(request, body.email)

    if not user or not verify_password(body.password, user.password_hash):
        await log_auth_event(
            db,
            event_type="login_failed",
            request=request,
            user=user,
            email=body.email,
            details={"reason": "invalid_credentials"},
        )
        await db.commit()
        await enforce_rate_limit(
            failure_key,
            settings.RATE_LIMIT_LOGIN_ATTEMPTS,
            settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
            "Слишком много неудачных попыток входа. Повторите позже.",
        )
        raise HTTPException(401, "Неверный email или пароль")

    if not user.is_active:
        await log_auth_event(
            db,
            event_type="login_failed",
            request=request,
            user=user,
            details={"reason": "inactive"},
        )
        await db.commit()
        raise HTTPException(403, "Аккаунт заблокирован")

    await clear_rate_limit(failure_key)
    user.last_login_at = utcnow()
    _, raw_refresh_token, access_token = await create_session(db, user=user, request=request)
    await log_auth_event(db, event_type="login_success", request=request, user=user)
    await db.commit()

    set_auth_cookies(response, access_token=access_token, refresh_token=raw_refresh_token)
    payload = user_dict(user)
    return AuthResponse(
        user=payload,
        email_verified=payload.email_verified,
        requires_email_verification=not payload.email_verified,
    )


@router.post("/refresh", status_code=204)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    session = await get_active_session_by_refresh_token(db, refresh_token)
    if session is None:
        clear_auth_cookies(response)
        raise HTTPException(401, "Refresh-сессия недействительна")

    user = await db.get(User, session.user_id)
    if not user or not user.is_active:
        await revoke_session(db, session)
        await db.commit()
        clear_auth_cookies(response)
        raise HTTPException(401, "Пользователь не найден")

    _, new_refresh_token, access_token = await rotate_session(db, current_session=session, request=request)
    await log_auth_event(db, event_type="refresh", request=request, user=user)
    await db.commit()
    set_auth_cookies(response, access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    session = await get_active_session_by_refresh_token(db, refresh_token)
    user = await db.get(User, session.user_id) if session else None
    await revoke_session(db, session)
    if user is not None:
        await log_auth_event(db, event_type="logout", request=request, user=user)
    await db.commit()
    clear_auth_cookies(response)


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token = await consume_email_verification_token(db, token=body.token)
    if token is None:
        raise HTTPException(400, "Ссылка подтверждения недействительна или истекла")

    user = await db.get(User, token.user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    await log_auth_event(db, event_type="verify_email", request=request, user=user)
    await db.commit()
    return {"verified": True}


@router.post("/resend-verification", status_code=204)
async def resend_verification(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if is_effectively_email_verified(current_user):
        raise HTTPException(409, "Email уже подтверждён")

    await enforce_rate_limit(
        _email_ip_key("auth:resend-verification", request, current_user.email),
        settings.RATE_LIMIT_PASSWORD_ATTEMPTS,
        settings.RATE_LIMIT_PASSWORD_WINDOW_SECONDS,
        "Слишком много запросов на повторную отправку. Повторите позже.",
    )

    verification_token = await issue_email_verification_token(db, user_id=current_user.id)
    await log_auth_event(db, event_type="resend_verification", request=request, user=current_user)
    await db.commit()
    sent, provider, error = await _send_verification_email_safe(email=current_user.email, token=verification_token)
    await _log_email_delivery_event_safe(
        db=db,
        request=request,
        event_type="email_sent" if sent else "email_failed",
        email_kind="verification",
        provider=provider,
        user=current_user,
        error=error,
    )


@router.post("/forgot-password", status_code=204)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        _email_ip_key("auth:forgot-password", request, body.email),
        settings.RATE_LIMIT_PASSWORD_ATTEMPTS,
        settings.RATE_LIMIT_PASSWORD_WINDOW_SECONDS,
        "Слишком много запросов на сброс пароля. Повторите позже.",
    )

    user = await db.scalar(select(User).where(User.email == body.email))
    if user is not None:
        reset_token = await issue_password_reset_token(db, user_id=user.id)
        await log_auth_event(db, event_type="forgot_password", request=request, user=user)
        await db.commit()
        sent, provider, error = await _send_password_reset_email_safe(email=user.email, token=reset_token)
        await _log_email_delivery_event_safe(
            db=db,
            request=request,
            event_type="email_sent" if sent else "email_failed",
            email_kind="password_reset",
            provider=provider,
            user=user,
            error=error,
        )
        return

    await log_auth_event(db, event_type="forgot_password", request=request, email=body.email, details={"user_found": False})
    await db.commit()


@router.post("/reset-password", status_code=204)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        _scoped_ip_key("auth:reset-password", request),
        settings.RATE_LIMIT_PASSWORD_ATTEMPTS,
        settings.RATE_LIMIT_PASSWORD_WINDOW_SECONDS,
        "Слишком много попыток сброса пароля. Повторите позже.",
    )

    token = await consume_password_reset_token(db, token=body.token)
    if token is None:
        raise HTTPException(400, "Ссылка сброса пароля недействительна или истекла")

    user = await db.get(User, token.user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")

    user.password_hash = hash_password(body.new_password)
    await revoke_all_user_sessions(db, user.id)
    await log_auth_event(db, event_type="reset_password", request=request, user=user)
    await db.commit()
    clear_auth_cookies(response)


@router.get("/me", response_model=MeResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    members = await db.scalars(select(ProjectMember).where(ProjectMember.user_id == current_user.id))
    payload = user_dict(current_user)
    return MeResponse(
        **payload.model_dump(),
        projects=[{"project_id": m.project_id, "role": m.role} for m in members],
    )


@router.patch("/me", response_model=AuthUserResponse)
async def update_me(
    body: MeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.name is not None:
        current_user.name = body.name
    if body.avatar_url is not None:
        current_user.avatar_url = body.avatar_url
    await db.commit()
    return user_dict(current_user)


@router.patch("/me/password", status_code=204)
async def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(400, "Неверный текущий пароль")
    current_user.password_hash = hash_password(body.new_password)
    await revoke_all_user_sessions(db, current_user.id)
    await log_auth_event(db, event_type="password_change", request=request, user=current_user)
    await db.commit()
    clear_auth_cookies(response)
