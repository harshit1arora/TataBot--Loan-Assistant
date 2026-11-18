"""Liveness and readiness. Readiness includes the core service."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response

from ..config import Settings, get_settings
from ..schemas import HealthResponse

router = APIRouter(tags=["ops"])
VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name, version=VERSION, checks={})


@router.get("/ready", response_model=HealthResponse)
async def ready(response: Response, settings: Settings = Depends(get_settings)) -> HealthResponse:
    checks = {"core_service": "unavailable"}
    try:
        import httpx

        async with httpx.AsyncClient(base_url=settings.core_base_url, timeout=2.0) as client:
            result = await client.get("/health")
        checks["core_service"] = "ok" if result.status_code == 200 else "degraded"
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        checks["core_service"] = "unavailable"

    if settings.agents_enabled:
        try:
            async with httpx.AsyncClient(base_url=settings.agents_base_url, timeout=4.0) as client:
                result = await client.get("/ready")
            checks["agents"] = "ok" if result.is_success and result.json()["status"] == "ok" else "degraded"
        except (httpx.HTTPError, KeyError, ValueError):
            checks["agents"] = "unavailable"

    status: Literal["ok", "degraded"] = (
        "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    )
    if status != "ok":
        response.status_code = 503
    return HealthResponse(status=status, service=settings.service_name, version=VERSION, checks=checks)
