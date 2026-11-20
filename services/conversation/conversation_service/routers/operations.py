"""Authenticated aggregate metrics from persisted agent traces."""

import hmac
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import TurnTrace

router = APIRouter()


@router.get("/internal/operations")
def operations(x_monitor_token: str = Header(default=""), db: Session = Depends(get_db)):
    expected = get_settings().core_client_secret
    if not x_monitor_token or not hmac.compare_digest(x_monitor_token, expected):
        raise HTTPException(401, "Service credential required.")
    traces = db.scalars(
        select(TurnTrace.detail)
        .where(TurnTrace.created_at >= datetime.now(UTC) - timedelta(hours=24))
        .order_by(TurnTrace.created_at.desc())
        .limit(10000)
    )
    turns = fallbacks = timeouts = failed_tools = 0
    for trace in traces:
        turns += 1
        details = [trace.get("router_detail", {}), *trace.get("workers", {}).values()]
        fallbacks += any(item.get("fallback") not in (None, "rules_configured") for item in details)
        timeouts += sum(item.get("fallback") == "provider_timeout" for item in details)
        failed_tools += sum(
            tool.get("status") == "failed" for item in details for tool in item.get("tools", [])
        )
    return {
        "turns": turns,
        "fallback_turns": fallbacks,
        "provider_timeouts": timeouts,
        "failed_tools": failed_tools,
        "window_hours": 24,
        "max_turns": 10000,
    }
