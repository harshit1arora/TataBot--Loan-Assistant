"""Agent service contracts."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryRequest(StrictModel):
    question: Annotated[str, Field(min_length=2, max_length=1000)]
    customer_id: Annotated[str | None, Field(default=None, pattern=r"^CUST\d{3,}$")] = None
    document_id: str | None = None


class StepView(BaseModel):
    at: str
    text: str


class QueryResponse(BaseModel):
    answer: str
    route: list[str]
    route_reason: str
    decided_by: Literal["rules", "llm:groq", "llm:gemini"] | str
    steps: list[str]
    citations: list[str]
    needs_input: list[str] = []
    data: dict = {}


class GraphView(BaseModel):
    entry: str
    nodes: list[str]
    edges: list[dict]
    workers: dict[str, str]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    llm: str
    mcp_transport: str
    checks: dict[str, str] = {}
