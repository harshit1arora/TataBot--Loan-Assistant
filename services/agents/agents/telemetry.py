from contextvars import ContextVar

active_worker: ContextVar[dict | None] = ContextVar("active_worker", default=None)
router_event: ContextVar[dict | None] = ContextVar("router_event", default=None)
deadline: ContextVar[float] = ContextVar("turn_deadline", default=float("inf"))
