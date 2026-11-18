"""A single provider budget shared by all agent replicas through Redis."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager

from .telemetry import deadline

# Redis owns the clock. The sorted set expires abandoned leases after the call deadline.
_ACQUIRE = """
local now = redis.call('TIME')
local ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ms)
if tonumber(redis.call('GET', KEYS[1]) or 0) >= tonumber(ARGV[1])
   or redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[2]) then return 0 end
if redis.call('INCR', KEYS[1]) == 1 then redis.call('EXPIRE', KEYS[1], 60) end
redis.call('ZADD', KEYS[2], ms + tonumber(ARGV[3]), ARGV[4])
redis.call('PEXPIRE', KEYS[2], tonumber(ARGV[3]) + 1000)
return 1
"""


class BudgetUnavailable(RuntimeError):
    pass


@asynccontextmanager
async def model_call(provider: str, seconds: float):
    url = os.getenv("REDIS_URL")
    remaining = min(seconds, deadline.get() - time.monotonic())
    async with asyncio.timeout(max(0, remaining)):
        if not url:
            if os.getenv("ENV", "").lower() in {"prod", "production"}:
                raise BudgetUnavailable("shared provider budget unavailable")
            yield
            return
        from redis.asyncio import Redis

        lease = uuid.uuid4().hex
        prefix = f"tatabot:{{model-{provider}}}"
        async with Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1) as redis:
            acquired = await redis.eval(
                _ACQUIRE,
                2,
                prefix + ":calls",
                prefix + ":inflight",
                int(os.getenv("MODEL_CALLS_PER_MINUTE", "20")),
                int(os.getenv("MODEL_MAX_CONCURRENT", "4")),
                int(seconds * 1000) + 1000,
                lease,
            )
            if not acquired:
                raise BudgetUnavailable("shared provider budget exhausted")
            try:
                yield
            finally:
                await redis.zrem(prefix + ":inflight", lease)
