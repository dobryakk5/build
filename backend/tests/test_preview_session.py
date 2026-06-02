"""Preview-session idempotency. Uses a real Redis; skipped if unavailable."""
from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings


def _redis_available() -> bool:
    try:
        import redis
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3)
        client.ping()
        client.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _redis_available(), reason="Redis not available"),
]


@pytest.fixture(autouse=True)
def _reset_redis_client():
    # The module caches one async client bound to the event loop that created it.
    # pytest-asyncio gives each test a fresh loop, so reset the cache per test.
    import app.core.redis as r
    r._redis_client = None
    yield
    r._redis_client = None


def _payload():
    return {
        "project_id": "p1", "user_id": "u1", "tmp_path": "/tmp/x.xlsx",
        "filename": "x.xlsx", "parser_profile": "pdf_materials_labor",
        "build_gantt": True, "estimate_kind": 1, "start_date": "2026-06-02",
        "workers": 3, "complex_mode": False, "clarification_answers": None,
        "type_breakdown": {},
    }


async def test_save_get_roundtrip():
    from app.services import preview_session as ps
    pid = await ps.save_preview_session(_payload())
    got = await ps.get_preview_session(pid)
    assert got and got["project_id"] == "p1" and got["status"] == "ready"


async def test_consume_is_idempotent():
    from app.services import preview_session as ps
    pid = await ps.save_preview_session(_payload())

    assert await ps.try_consume_preview_session(pid) == "consumed"
    # Second confirm of the same preview must be rejected.
    assert await ps.try_consume_preview_session(pid) == "already_consumed"


async def test_consume_missing():
    from app.services import preview_session as ps
    assert await ps.try_consume_preview_session("imp_does_not_exist") == "missing"
