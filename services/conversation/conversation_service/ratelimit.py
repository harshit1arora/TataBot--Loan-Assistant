"""Per-customer sliding-window rate limit (in-process; see the core service note)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

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


def enforce(key: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    now = time.monotonic()
    bucket = _hits[key]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= settings.rate_limit_per_minute:
        raise RateLimited(details={"limit": settings.rate_limit_per_minute})
    bucket.append(now)
