"""Per-customer sliding-window rate limit (in-process; see the core service note)."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from functools import lru_cache

from redis import Redis, RedisError

from .config import Settings, get_settings
from .errors import AppError

_WINDOW_SECONDS = 60
_hits: dict[str, deque[float]] = defaultdict(deque)


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many messages. Please slow down."


def reset() -> None:
    _hits.clear()


@lru_cache(maxsize=1)
def _shared(url: str) -> Redis:
    return Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)


def enforce(key: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    url = os.getenv("REDIS_URL")
    if url:
        counter = f"tatabot:conversation:requests:{key}"
        try:
            count = _shared(url).eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
                1, counter,
            )
        except RedisError as exc:
            raise RateLimited("Request budget unavailable.") from exc
        if int(count) > settings.rate_limit_per_minute:
            raise RateLimited()
        return
    now = time.monotonic()
    bucket = _hits[key]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= settings.rate_limit_per_minute:
        raise RateLimited(details={"limit": settings.rate_limit_per_minute})
    bucket.append(now)
