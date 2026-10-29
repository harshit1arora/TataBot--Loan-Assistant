"""API contracts for the conversation service."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Note what is absent: no current_state, no customer_id, no amount.

    Identity comes from the bearer token and the workflow position comes from the
    server-side session, so a caller cannot influence either.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, max_length=64)
    message: Annotated[str, Field(min_length=1, max_length=1000)]


class ChatResponse(BaseModel):
    session_id: str
    state: str
    reply: str
    application: dict | None = None
    document: dict | None = None
    sanction_document_id: str | None = None
    suggested_actions: list[str] = []
    # Set when the reply is a side channel (e.g. "contact", "agents") rather than a step.
    intent: str | None = None
    # Which specialist agents answered, when the question was delegated.
    agent_route: list[str] = []
    citations: list[str] = []


class MessageView(BaseModel):
    role: str
    content: str
    created_at: str


class SessionView(BaseModel):
    session_id: str
    state: str
    customer_id: str
    application: dict | None = None
    created_at: str
    updated_at: str


class SessionSummary(BaseModel):
    """One row in the customer's conversation history."""

    session_id: str
    state: str
    created_at: str
    updated_at: str
    message_count: int
    last_message: str | None = None
    last_role: str | None = None
    application_id: str | None = None
    requested_amount_paise: int | None = None


class SessionList(BaseModel):
    sessions: list[SessionSummary]
    total: int


class TraceStep(BaseModel):
    at: str
    from_state: str
    to_state: str
    event: str
    handled_by: str


class SessionTrace(BaseModel):
    """The routing history of one conversation, newest last."""

    session_id: str
    state: str
    application_id: str | None = None
    steps: list[TraceStep]
    messages: int


class UploadResponse(BaseModel):
    session_id: str
    state: str
    reply: str
    document: dict | None = None
    application: dict | None = None
    sanction_document_id: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    checks: dict[str, str]
