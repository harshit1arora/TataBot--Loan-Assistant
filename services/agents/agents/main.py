"""Agent service HTTP API.

Service-to-service only: the conversation service calls this with a shared token. It is not
a browser-facing API, because the agent layer holds tools that reach customer data.
"""
from __future__ import annotations

import hmac
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from .config import ROLES, key_report, settings
from .graph import AgentGraph
from .llm import build_llm
from .mcp_client import McpToolbox
from .schemas import GraphView, HealthResponse, QueryRequest, QueryResponse

SERVICE_TOKEN = os.environ.get(
    "AGENT_SERVICE_TOKEN", "agent-service-token-change-me"  # noqa: S105 - dev default
)


def require_service_token(x_service_token: Annotated[str | None, Header()] = None) -> None:
    if not x_service_token or not hmac.compare_digest(x_service_token, SERVICE_TOKEN):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="service token required")


@asynccontextmanager
async def lifespan(app: FastAPI):
    toolbox = McpToolbox(settings)
    llms = {role: build_llm(settings, role) for role in ROLES}
    app.state.graph = AgentGraph(settings, toolbox=toolbox, llms=llms)
    app.state.llm_name = next((client.name for client in llms.values() if client.available), "rules")
    app.state.llm_keys = key_report(settings)
    yield


app = FastAPI(
    title="TataBot Agent Service",
    version="1.0.0",
    description="LangGraph orchestrator over four specialised loan agents, calling MCP tools.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    graph: AgentGraph = app.state.graph
    return HealthResponse(
        status="ok",
        service="agents",
        llm=app.state.llm_name,
        mcp_transport=settings.mcp_transport,
        checks={
            "workers": str(len(graph.workers)),
            "llm_roles": ",".join(
                f"{role}:{state}" for role, state in (app.state.llm_keys or {}).items()
            ),
        },
    )


@app.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    """Readiness: can the graph actually see its tools?"""
    graph: AgentGraph = app.state.graph
    checks: dict[str, str] = {}
    try:
        tools = await graph.toolbox.available_tools()
        checks["mcp_tools"] = f"ok ({len(tools)})"
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        checks["mcp_tools"] = "unavailable"
    status: Literal["ok", "degraded"] = (
        "ok" if checks["mcp_tools"].startswith("ok") else "degraded"
    )
    return HealthResponse(
        status=status,
        service="agents",
        llm=app.state.llm_name,
        mcp_transport=settings.mcp_transport,
        checks=checks,
    )


@app.get("/agent/models")
def models(request: Request) -> dict:
    """Which model each role uses, and whether it has its own key. Never the key itself."""
    graph: AgentGraph = request.app.state.graph
    return {
        "provider": settings.llm_provider,
        "model": settings.groq_model if settings.llm_provider == "groq" else settings.gemini_model,
        "roles": graph.llm_summary(),
        "keys": request.app.state.llm_keys,
    }


@app.get("/agent/graph", response_model=GraphView)
def graph_topology() -> GraphView:
    """The compiled graph, for inspection: nodes, edges and worker scopes."""
    graph: AgentGraph = app.state.graph
    return GraphView(**graph.topology())


@app.post("/agent/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    request: Request,
    _: None = Depends(require_service_token),
) -> QueryResponse:
    graph: AgentGraph = request.app.state.graph
    question = payload.question.strip()[: settings.max_question_chars]

    started = time.perf_counter()
    result = await graph.run(question, payload.customer_id, payload.document_id)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    steps = list(result.get("steps", []))
    steps.append(f"synthesise: {len(result.get('route', []))} worker(s) in {elapsed_ms} ms")

    # Flatten the per-worker structured data for the caller.
    data = {
        name: payload_result.get("data", {})
        for name, payload_result in (result.get("results") or {}).items()
        if payload_result.get("data")
    }

    return QueryResponse(
        answer=result.get("answer", ""),
        route=result.get("route", []),
        route_reason=result.get("route_reason", ""),
        decided_by=result.get("steps", ["rules"])[0].split("(")[1].split(")")[0]
        if result.get("steps") and "(" in result["steps"][0]
        else "rules",
        steps=steps,
        citations=result.get("citations", []),
        needs_input=result.get("needs_input", []),
        data=data,
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-agent-duration-ms"] = str(round((time.perf_counter() - started) * 1000, 1))
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Agent turn failed.",
                           "at": datetime.now(UTC).isoformat()}},
    )
