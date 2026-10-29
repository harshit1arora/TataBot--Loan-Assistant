"""Liveness, readiness and metrics."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..schemas import HealthResponse

router = APIRouter(tags=["ops"])

VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Liveness: is the process up? Never touches dependencies."""
    return HealthResponse(
        status="ok", service=settings.service_name, version=VERSION, checks={},
        time=datetime.now(UTC),
    )


@router.get("/ready", response_model=HealthResponse)
def ready(
    response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> HealthResponse:
    """Readiness: can this instance actually serve traffic?"""
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - readiness reports, it does not raise
        checks["database"] = "unavailable"
    try:
        Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
        checks["storage"] = "ok"
    except Exception:  # noqa: BLE001
        checks["storage"] = "unavailable"

    status: Literal["ok", "degraded"] = (
        "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    )
    if status != "ok":
        response.status_code = 503
    return HealthResponse(
        status=status, service=settings.service_name, version=VERSION, checks=checks,
        time=datetime.now(UTC),
    )


@router.get("/metrics")
def metrics() -> Response:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
