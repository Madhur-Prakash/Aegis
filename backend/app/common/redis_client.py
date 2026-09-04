"""Redis: distributed locks, rate limiting, cache.  Never authoritative state.

If Redis is flushed the application loses nothing but cache warmth.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis

from app.common.errors import Conflict, RateLimited
from app.common.logging import get_logger
from app.config.settings import settings

log = get_logger("redis")

_client: aioredis.Redis | None = None

# Release only if the token still matches -- never a naked DEL.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, math.ceil(window - (now - tonumber(oldest[2])))}
end
redis.call('ZADD', key, now, now .. ':' .. ARGV[4])
redis.call('EXPIRE', key, window)
return {1, 0}
"""


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True, socket_timeout=3
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def redis_ready() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


@asynccontextmanager
async def distributed_lock(
    key: str, ttl_ms: int = 15_000, *, required: bool = True
) -> AsyncIterator[bool]:
    """``SET NX PX`` with a token and a safe release.

    This is the belt to the DB unique index's braces (I6).  If Redis is down the
    lock is skipped and the database constraint still guarantees exactly one
    payout -- correctness never depends on the cache being up.
    """
    token = secrets.token_hex(16)
    full = f"aegis:lock:{key}"
    acquired = False
    client = get_redis()
    try:
        acquired = bool(await client.set(full, token, nx=True, px=ttl_ms))
    except Exception as exc:
        log.warning("lock unavailable", extra={"key": key, "error": type(exc).__name__})
        yield False
        return
    if not acquired and required:
        raise Conflict(
            code="OPERATION_IN_PROGRESS",
            message="Another operation on this milestone is in progress.",
            details={"key": key},
        )
    try:
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(Exception):  # pragma: no cover
                await client.eval(_RELEASE_LUA, 1, full, token)  # type: ignore[misc]


async def rate_limit(bucket: str, identity: str, spec: str) -> None:
    """Sliding window per identity.  ``spec`` is ``"<limit>/<window_seconds>"``."""
    limit_s, window_s = spec.split("/")
    limit, window = int(limit_s), int(window_s)
    key = f"aegis:rl:{bucket}:{identity}"
    try:
        result: Any = await get_redis().eval(  # type: ignore[misc]
            _SLIDING_WINDOW_LUA,
            1,
            key,
            str(time.time()),
            str(window),
            str(limit),
            secrets.token_hex(4),
        )
        allowed, retry_after = result
    except Exception:
        return  # rate limiting degrades open; it is not a safety invariant
    if not int(allowed):
        raise RateLimited(
            message="Too many requests. Try again shortly.",
            details={
                "bucket": bucket,
                "limit": limit,
                "window_seconds": window,
                "retry_after": int(retry_after),
            },
        )


async def cache_get_json(key: str) -> Any | None:
    try:
        raw = await get_redis().get(f"aegis:cache:{key}")
    except Exception:
        return None
    return json.loads(raw) if raw else None


async def cache_set_json(key: str, value: Any, ttl_s: int = 120) -> None:
    try:
        await get_redis().set(f"aegis:cache:{key}", json.dumps(value, default=str), ex=ttl_s)
    except Exception:
        return
