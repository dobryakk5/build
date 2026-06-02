"""Short-lived import preview sessions, stored in Redis.

A preview parses the uploaded file to a tmp path and shows the operator the
typed breakdown WITHOUT touching the DB. The real server tmp path is never
exposed to the client — the client only gets an opaque ``preview_id``. Confirm
looks the session up, checks ownership/TTL, and atomically marks it consumed so
the same preview can't be imported twice.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from redis.exceptions import RedisError, WatchError

from app.core.redis import init_redis

PREVIEW_TTL_SECONDS = 3600
_KEY_PREFIX = "estimate_preview:"

STATUS_READY = "ready"
STATUS_CONSUMED = "consumed"


class PreviewStorageUnavailable(Exception):
    """Redis is unavailable — the route maps this to HTTP 503."""


def _key(preview_id: str) -> str:
    return f"{_KEY_PREFIX}{preview_id}"


async def save_preview_session(payload: dict) -> str:
    """Create a session, return its preview_id."""
    preview_id = f"imp_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    record = {
        **payload,
        "preview_id": preview_id,
        "status": STATUS_READY,
        "job_id": None,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
    }
    try:
        redis = await init_redis()
        await redis.set(_key(preview_id), json.dumps(record), ex=PREVIEW_TTL_SECONDS)
    except RedisError as exc:  # pragma: no cover - infra failure
        raise PreviewStorageUnavailable(str(exc)) from exc
    return preview_id


async def get_preview_session(preview_id: str) -> dict | None:
    try:
        redis = await init_redis()
        raw = await redis.get(_key(preview_id))
    except RedisError as exc:  # pragma: no cover
        raise PreviewStorageUnavailable(str(exc)) from exc
    return json.loads(raw) if raw else None


async def try_consume_preview_session(preview_id: str) -> str:
    """Atomically flip ready→consumed.

    Returns "consumed" on success, "already_consumed" if it was already taken,
    or "missing" if the session is gone/expired.
    """
    try:
        redis = await init_redis()
        async with redis.pipeline() as pipe:
            while True:
                try:
                    await pipe.watch(_key(preview_id))
                    raw = await pipe.get(_key(preview_id))
                    if raw is None:
                        await pipe.unwatch()
                        return "missing"
                    data = json.loads(raw)
                    if data.get("status") == STATUS_CONSUMED:
                        await pipe.unwatch()
                        return "already_consumed"
                    ttl = await pipe.ttl(_key(preview_id))
                    data["status"] = STATUS_CONSUMED
                    pipe.multi()
                    pipe.set(
                        _key(preview_id),
                        json.dumps(data),
                        ex=ttl if ttl and ttl > 0 else PREVIEW_TTL_SECONDS,
                    )
                    await pipe.execute()
                    return "consumed"
                except WatchError:  # pragma: no cover - concurrent confirm
                    continue
    except RedisError as exc:  # pragma: no cover
        raise PreviewStorageUnavailable(str(exc)) from exc


async def update_preview_session(preview_id: str, **fields) -> None:
    """Best-effort merge of fields (e.g. job_id) into an existing session."""
    try:
        redis = await init_redis()
        raw = await redis.get(_key(preview_id))
        if not raw:
            return
        data = json.loads(raw)
        data.update(fields)
        ttl = await redis.ttl(_key(preview_id))
        await redis.set(
            _key(preview_id),
            json.dumps(data),
            ex=ttl if ttl and ttl > 0 else PREVIEW_TTL_SECONDS,
        )
    except RedisError as exc:  # pragma: no cover
        raise PreviewStorageUnavailable(str(exc)) from exc


async def set_preview_status(preview_id: str, status: str) -> None:
    """Used to roll a session back to ready if job creation failed."""
    await update_preview_session(preview_id, status=status)
