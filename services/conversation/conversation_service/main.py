"""Conversation service entrypoint: wiring, middleware and error handling only."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agents_client import AgentsClient
from .clients import CoreClient
from .config import get_settings
from .db import create_all
from .errors import AppError
from .llm import LlmClient
from .logging_setup import configure_logging, get_logger, request_id_var
from .orchestrator import Orchestrator
from .routers import chat, health

settings = get_settings()
configure_logging(settings.log_level, settings.service_name)
logger = get_logger("conversation.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    app.state.orchestrator = Orchestrator(
        settings, CoreClient(settings), LlmClient(settings), AgentsClient(settings)
    )
    logger.info(
        "startup complete",
        extra={"event": "startup", "llm_enabled": app.state.orchestrator.llm.enabled},
    )
    yield
    logger.info("shutdown", extra={"event": "shutdown"})


app = FastAPI(
    title="TataBot Conversation Service",
    version="1.0.0",
    description=(
        "Conversational front door. Owns the workflow state machine and the wording; "
        "owns no customer data and makes no credit decision."
    ),
    lifespan=lifespan,
    docs_url="/docs" if settings.env != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["cache-control"] = "no-store"
    logger.info(
        "request",
        extra={
            "event": "http_request",
            "path": request.url.path,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_failed",
                "message": "The request body failed validation.",
                "request_id": request_id_var.get(),
                "details": [
                    {"field": ".".join(str(p) for p in err["loc"][1:]), "problem": err["msg"]}
                    for err in exc.errors()
                ],
            }
        },
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id_var.get(),
                "details": exc.details,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error", extra={"event": "unhandled_error", "path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred. Quote the request id if you contact support.",
                "request_id": request_id_var.get(),
            }
        },
    )


app.include_router(health.router)
app.include_router(chat.router)
