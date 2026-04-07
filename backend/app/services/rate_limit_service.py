import logging

from fastapi import HTTPException

from app.core.redis import get_redis_client


logger = logging.getLogger(__name__)


async def enforce_rate_limit(key: str, limit: int, window_seconds: int, detail: str) -> None:
    redis = get_redis_client()
    if redis is None:
        return

    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window_seconds)
        if current > limit:
            raise HTTPException(status_code=429, detail=detail)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Rate limiter degraded for key %s", key)


async def clear_rate_limit(key: str) -> None:
    redis = get_redis_client()
    if redis is None:
        return

    try:
        await redis.delete(key)
    except Exception:
        logger.exception("Failed to clear rate limit key %s", key)
