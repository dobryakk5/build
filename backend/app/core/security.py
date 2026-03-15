"""Password hashing и JWT утилиты — единственное место в проекте."""
from datetime import datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    return jwt.encode(
        {
            "sub":  user_id,
            "exp":  datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            "iat":  datetime.utcnow(),
            "type": "access",
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def create_refresh_token(user_id: str) -> str:
    return jwt.encode(
        {
            "sub":  user_id,
            "exp":  datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            "iat":  datetime.utcnow(),
            "type": "refresh",
            "jti":  str(uuid4()),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict:
    """Бросает jwt.InvalidTokenError при невалидном или истёкшем токене."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
