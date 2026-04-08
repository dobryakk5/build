from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi import HTTPException, Response
import pytest

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
