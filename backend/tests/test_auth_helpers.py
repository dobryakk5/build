from pathlib import Path
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException, Response
import pytest
from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core import redis as redis_module
from app.services.auth_service import clear_auth_cookies, hash_token, is_effectively_email_verified, set_auth_cookies
from app.services.rate_limit_service import clear_rate_limit, enforce_rate_limit


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.deleted: list[str] = []

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_enforce_rate_limit_blocks_after_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = FakeRedis()
    monkeypatch.setattr(redis_module, "_redis_client", fake_redis)

    await enforce_rate_limit("auth:test", 2, 60, "blocked")
    await enforce_rate_limit("auth:test", 2, 60, "blocked")

    with pytest.raises(HTTPException) as exc:
        await enforce_rate_limit("auth:test", 2, 60, "blocked")

    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_clear_rate_limit_removes_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = FakeRedis()
    fake_redis.values["auth:test"] = 3
    monkeypatch.setattr(redis_module, "_redis_client", fake_redis)

    await clear_rate_limit("auth:test")

    assert "auth:test" in fake_redis.deleted
    assert "auth:test" not in fake_redis.values


def test_set_and_clear_auth_cookies() -> None:
    response = Response()

    set_auth_cookies(response, access_token="access", refresh_token="refresh")
    raw_cookie = "\n".join(response.raw_headers[i][1].decode() for i in range(len(response.raw_headers)))
    assert "access_token=access" in raw_cookie
    assert "refresh_token=refresh" in raw_cookie
    assert "HttpOnly" in raw_cookie

    clear_auth_cookies(response)
    cleared_cookie = "\n".join(response.raw_headers[i][1].decode() for i in range(len(response.raw_headers)))
    assert "Max-Age=0" in cleared_cookie


def test_hash_token_is_deterministic_and_opaque() -> None:
    hashed = hash_token("plain-token")

    assert hashed == hash_token("plain-token")
    assert hashed != "plain-token"
    assert len(hashed) == 64


def test_effective_email_verification_allows_seed_test_account() -> None:
    test_user = SimpleNamespace(email="test@example.com", email_verified_at=None)
    regular_user = SimpleNamespace(email="user@example.com", email_verified_at=None)

    assert is_effectively_email_verified(test_user) is True
    assert is_effectively_email_verified(regular_user) is False


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/test",
            "headers": [(b"user-agent", b"pytest-agent")],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.asyncio
async def test_log_email_delivery_event_safe_commits_audit_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import auth as auth_routes

    captured: dict[str, object] = {}
    db = AsyncMock()

    async def fake_log_auth_event(db_arg, **kwargs):
        captured["db"] = db_arg
        captured["kwargs"] = kwargs

    monkeypatch.setattr(auth_routes, "log_auth_event", fake_log_auth_event)

    user = SimpleNamespace(id="user-1", email="user@example.com")
    await auth_routes._log_email_delivery_event_safe(
        db=db,
        request=_request(),
        event_type="email_failed",
        email_kind="verification",
        provider="smtp",
        user=user,
        error="smtp timeout",
    )

    assert captured["db"] is db
    assert captured["kwargs"]["event_type"] == "email_failed"
    assert captured["kwargs"]["user"] is user
    assert captured["kwargs"]["details"] == {
        "email_type": "verification",
        "provider": "smtp",
        "error": "smtp timeout",
    }
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_email_delivery_event_safe_rolls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.api.routes import auth as auth_routes

    db = AsyncMock()

    async def fake_log_auth_event(db_arg, **kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(auth_routes, "log_auth_event", fake_log_auth_event)
    caplog.set_level(logging.ERROR, logger=auth_routes.logger.name)

    await auth_routes._log_email_delivery_event_safe(
        db=db,
        request=_request(),
        event_type="email_sent",
        email_kind="password_reset",
        provider="resend",
        email="user@example.com",
    )

    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()
    assert "Failed to persist auth audit event email_sent for password_reset email" in caplog.text


@pytest.mark.asyncio
async def test_send_verification_email_safe_returns_provider_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import auth as auth_routes

    async def fake_send_verification_email(*, to_email: str, token: str) -> str:
        assert to_email == "user@example.com"
        assert token == "token-123"
        return "resend"

    monkeypatch.setattr(auth_routes, "send_verification_email", fake_send_verification_email)

    assert await auth_routes._send_verification_email_safe(email="user@example.com", token="token-123") == (
        True,
        "resend",
        None,
    )


@pytest.mark.asyncio
async def test_send_password_reset_email_safe_returns_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import auth as auth_routes

    async def fake_send_password_reset_email(*, to_email: str, token: str) -> str:
        raise RuntimeError("smtp unavailable")

    monkeypatch.setattr(auth_routes, "send_password_reset_email", fake_send_password_reset_email)
    monkeypatch.setattr(auth_routes, "resolve_email_provider", lambda: "smtp")

    assert await auth_routes._send_password_reset_email_safe(email="user@example.com", token="token-123") == (
        False,
        "smtp",
        "smtp unavailable",
    )
