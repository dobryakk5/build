"""Password hashing и JWT утилиты — единственное место в проекте."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id) -> str:
    now = _now()
    return jwt.encode(
        {
            "sub":  str(user_id),
            "exp":  now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            "iat":  now,
            "type": "access",
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def create_refresh_token(user_id) -> str:
    now = _now()
    return jwt.encode(
        {
            "sub":  str(user_id),
            "exp":  now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            "iat":  now,
            "type": "refresh",
            "jti":  str(uuid4()),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict:
    """Бросает jwt.InvalidTokenError при невалидном или истёкшем токене."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


def decode_access_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise ValueError(f"Expected access token, got: {payload.get('type')!r}")
    return payload


def decode_refresh_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise ValueError(f"Expected refresh token, got: {payload.get('type')!r}")
    return payload
