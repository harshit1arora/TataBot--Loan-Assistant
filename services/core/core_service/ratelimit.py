"""Per-caller sliding-window rate limit.

In-process, which is correct for a single instance and a documented limitation beyond
that: move the counter into Redis (INCR + EXPIRE on a windowed key) when you scale out.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Request

from .config import Settings, get_settings
from .errors import RateLimited
from .security import Principal, decode_token

_WINDOW_SECONDS = 60
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset() -> None:
    _hits.clear()


def _client_key(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            principal: Principal = decode_token(
                header.split(" ", 1)[1].strip(), get_settings()
            )
            return f"{principal.scope}:{principal.subject}"
        except Exception:  # noqa: BLE001 - fall through to IP for unauthenticated callers
            logging.getLogger("core.ratelimit").debug("token decode failed; keying on IP")
    settings = get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def enforce(request: Request, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    limit = settings.rate_limit_per_minute
    now = time.monotonic()
    bucket = _hits[_client_key(request)]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit:
        raise RateLimited(details={"limit": limit, "window_seconds": _WINDOW_SECONDS})
    bucket.append(now)
