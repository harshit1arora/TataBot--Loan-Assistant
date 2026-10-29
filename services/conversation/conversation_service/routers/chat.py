"""Chat, session status, transcript and document upload."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth import Principal, get_principal
from ..config import Settings, get_settings
from ..db import get_db
from ..errors import ConflictError, NotFoundError, ValidationAppError
from ..models import ConversationSession, Message, Transition
from ..orchestrator import Orchestrator
from ..schemas import (
    ChatRequest,
    ChatResponse,
    MessageView,
    SessionList,
    SessionSummary,
    SessionTrace,
    SessionView,
    TraceStep,
    UploadResponse,
)
from ..workflow import Event, TransitionNotAllowed, handled_by

router = APIRouter(tags=["chat"])


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def _bearer(request: Request) -> str:
    return request.headers["authorization"].split(" ", 1)[1].strip()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    ratelimit.enforce(f"chat:{principal.customer_id}", settings)
    try:
        result = await orchestrator.handle_message(
            db,
            customer_id=principal.customer_id,
            customer_token=_bearer(request),
            session_id=payload.session_id,
            message=payload.message,
        )
    except TransitionNotAllowed as exc:
        # Defensive: a transition the table forbids is a conflict, not a server fault.
        raise ConflictError(
            "That action is not available at this point in the conversation.",
            details={"state": exc.state.value},
        ) from exc
    return ChatResponse(**result.to_dict())


@router.get("/sessions", response_model=SessionList)
def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SessionList:
    """The signed-in customer's conversations, newest first.

    This is what makes the assistant feel continuous: the transcript is already stored,
    so returning to the app can show what was discussed last time.
    """
    rows = (
        db.query(ConversationSession)
        .filter(ConversationSession.customer_id == principal.customer_id)
        .order_by(ConversationSession.updated_at.desc())
        .limit(limit)
        .all()
    )

    summaries: list[SessionSummary] = []
    for row in rows:
        messages = (
            db.query(Message)
            .filter(Message.session_id == row.id)
            .order_by(Message.created_at.desc())
            .limit(1)
            .all()
        )
        count = db.query(Message).filter(Message.session_id == row.id).count()
        last = messages[0] if messages else None
        summaries.append(
            SessionSummary(
                session_id=row.id,
                state=row.state,
                created_at=row.created_at.isoformat(),
                updated_at=row.updated_at.isoformat(),
                message_count=count,
                last_message=(last.content[:140] if last else None),
                last_role=(last.role if last else None),
                application_id=row.application_id,
                requested_amount_paise=row.requested_amount_paise,
            )
        )

    return SessionList(sessions=summaries, total=len(summaries))


@router.get("/sessions/{session_id}", response_model=SessionView)
async def session_status(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> SessionView:
    session = db.get(ConversationSession, session_id)
    if session is None or session.customer_id != principal.customer_id:
        raise NotFoundError("Session not found.")
    body = await orchestrator.status(db, customer_token=_bearer(request), session_id=session_id)
    return SessionView(
        session_id=body["session_id"],
        state=body["state"],
        customer_id=body["customer_id"],
        application=body["application"],
        created_at=body["created_at"].isoformat(),
        updated_at=body["updated_at"].isoformat(),
    )


@router.get("/sessions/{session_id}/messages", response_model=list[MessageView])
def session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[MessageView]:
    session = db.get(ConversationSession, session_id)
    if session is None or session.customer_id != principal.customer_id:
        raise NotFoundError("Session not found.")
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at)
        .limit(200)
        .all()
    )
    return [
        MessageView(role=row.role, content=row.content, created_at=row.created_at.isoformat())
        for row in rows
    ]


@router.get("/sessions/{session_id}/trace", response_model=SessionTrace)
def session_trace(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SessionTrace:
    """Every state change, with the component that caused it.

    This is how you answer "is the orchestrator routing correctly?" without reading code:
    the sequence of transitions and their handlers is a query.
    """
    session = db.get(ConversationSession, session_id)
    if session is None or session.customer_id != principal.customer_id:
        raise NotFoundError("Session not found.")

    rows = (
        db.query(Transition)
        .filter(Transition.session_id == session_id)
        .order_by(Transition.created_at)
        .limit(200)
        .all()
    )
    message_count = db.query(Message).filter(Message.session_id == session_id).count()
    return SessionTrace(
        session_id=session.id,
        state=session.state,
        application_id=session.application_id,
        steps=[
            TraceStep(
                at=row.created_at.isoformat(),
                from_state=row.from_state,
                to_state=row.to_state,
                event=row.event,
                handled_by=handled_by(Event(row.event)),
            )
            for row in rows
        ],
        messages=message_count,
    )


@router.post("/sessions/{session_id}/documents", response_model=UploadResponse)
async def upload(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(default="salary_slip"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> UploadResponse:
    """Multipart upload — the shape the frontend actually sends."""
    ratelimit.enforce(f"upload:{principal.customer_id}", settings)
    chunks: list[bytes] = []
    total = 0
    limit = 6 * 1024 * 1024
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise ValidationAppError("File is too large.", details={"max_bytes": limit})
        chunks.append(chunk)

    try:
        result = await orchestrator.handle_upload(
            db,
            customer_id=principal.customer_id,
            customer_token=_bearer(request),
            session_id=session_id,
            filename=file.filename or "upload",
            content=b"".join(chunks),
            content_type=file.content_type or "application/octet-stream",
            doc_type=doc_type,
        )
    except TransitionNotAllowed as exc:
        raise ConflictError(
            "This conversation is not waiting for a document.",
            details={"state": exc.state.value},
        ) from exc

    return UploadResponse(
        session_id=result.session_id,
        state=result.state.value,
        reply=result.reply,
        document=result.document,
        application=result.application,
        sanction_document_id=result.sanction_document_id,
    )
