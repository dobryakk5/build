from pathlib import Path
import sys
import time

import jwt
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decode_token,
)


USER_ID = "test-user-uuid-1234"


def test_decode_access_token_accepts_valid_access_token():
    token = create_access_token(USER_ID)
    payload = decode_access_token(token)

    assert payload["sub"] == USER_ID
    assert payload["type"] == "access"


def test_decode_access_token_rejects_refresh_token():
    refresh = create_refresh_token(USER_ID)

    with pytest.raises(ValueError, match="access"):
        decode_access_token(refresh)


def test_decode_access_token_rejects_expired_token():
    expired = jwt.encode(
        {"sub": USER_ID, "type": "access", "exp": int(time.time()) - 10},
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


def test_decode_access_token_rejects_bad_signature():
    token = jwt.encode(
        {"sub": USER_ID, "type": "access", "exp": int(time.time()) + 300},
        "wrong-secret",
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token)


def test_decode_refresh_token_accepts_valid_refresh_token():
    token = create_refresh_token(USER_ID)
    payload = decode_refresh_token(token)

    assert payload["sub"] == USER_ID
    assert payload["type"] == "refresh"
    assert "jti" in payload


def test_decode_refresh_token_rejects_access_token():
    access = create_access_token(USER_ID)

    with pytest.raises(ValueError, match="refresh"):
        decode_refresh_token(access)


def test_decode_token_does_not_check_type():
    access = create_access_token(USER_ID)
    refresh = create_refresh_token(USER_ID)

    assert decode_token(access)["type"] == "access"
    assert decode_token(refresh)["type"] == "refresh"
