"""Core lending service — application entrypoint.

Wiring only: middleware, error handling, routers. Business logic lives in app/services
and the credit policy in app/policy.py.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import create_all, engine, session_scope
from .errors import AppError
from .logging_setup import configure_logging, get_logger, request_id_var
from .migrations import apply_additive_migrations
from .routers import applications, auth, customers, documents, health, internal, support
from .services import customers as customer_service

settings = get_settings()
configure_logging(settings.log_level, settings.service_name)
logger = get_logger("core.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    apply_additive_migrations(engine)
    with session_scope() as db:
        added = customer_service.seed(db)
    logger.info("startup complete", extra={"event": "startup", "customers_seeded": added})
    yield
    logger.info("shutdown", extra={"event": "shutdown"})


app = FastAPI(
    title="TataBot Core Lending Service",
    version="1.0.0",
    description=(
        "Customer data, credit policy, underwriting, documents and sanction letters. "
        "The conversation service has no direct access to any of it."
    ),
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)

# Explicit allowlist, no wildcard, and credentials only if you actually use cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    max_age=600,
)


_schema_ready = False


def _ensure_schema() -> None:
    """Create tables on first use.

    Lifespan handles this on a long-lived process. Serverless platforms may invoke the
    function without running lifespan, so this makes a cold start self-sufficient.
    """
    global _schema_ready
    if _schema_ready:
        return
    create_all()
    applied = apply_additive_migrations(engine)
    with session_scope() as db:
        customer_service.seed(db)
    if applied:
        logger.info("schema patched", extra={"event": "migration", "columns": applied})
    _schema_ready = True


@app.middleware("http")
async def request_context(request: Request, call_next):
    _ensure_schema()
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
    response.headers["cache-control"] = response.headers.get("cache-control", "no-store")
    logger.info(
        "request",
        extra={"event": "http_request", "path": request.url.path, "duration_ms": round(duration_ms, 2)},
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Schema failures get the same envelope as every other error."""
    request_id = request_id_var.get()
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_failed",
                "message": "The request body failed validation.",
                "request_id": request_id,
                "details": [
                    {"field": ".".join(str(part) for part in err["loc"][1:]), "problem": err["msg"]}
                    for err in exc.errors()
                ],
            }
        },
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = request_id_var.get()
    log = logger.warning if exc.status_code < 500 else logger.error
    log(
        "handled error",
        extra={"event": "app_error", "code": exc.code, "status": exc.status_code, "path": request.url.path},
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload(request_id))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internals: the client gets a code and a request id, we get the traceback."""
    request_id = request_id_var.get()
    logger.exception("unhandled error", extra={"event": "unhandled_error", "path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred. Quote the request id if you contact support.",
                "request_id": request_id,
            }
        },
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(applications.router)
app.include_router(documents.router)
app.include_router(internal.router)
app.include_router(support.router)
