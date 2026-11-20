"""Private, authenticated conversation data lifecycle operations."""
import hmac
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (ApplicationAttempt, ConversationSession, Message, PendingAgentQuestion,
                      SessionDocument, Transition, TurnTrace)

router = APIRouter(prefix="/internal/privacy")


def authorize(x_privacy_secret: str = Header(default="")):
    if not hmac.compare_digest(x_privacy_secret, get_settings().core_client_secret):
        raise HTTPException(401, "Invalid service credentials")


def delete_sessions(db: Session, ids: list[str]) -> int:
    if not ids:
        return 0
    for model in (Message, Transition, TurnTrace, PendingAgentQuestion, SessionDocument, ApplicationAttempt):
        db.execute(delete(model).where(model.session_id.in_(ids)))
    return db.execute(delete(ConversationSession).where(ConversationSession.id.in_(ids))).rowcount


class Erase(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)


class Retention(BaseModel):
    days: int = Field(ge=1)


@router.post("/erase", dependencies=[Depends(authorize)])
def erase(body: Erase, db: Session = Depends(get_db)):
    ids = list(db.scalars(select(ConversationSession.id).where(ConversationSession.customer_id == body.customer_id)))
    return {"sessions_deleted": delete_sessions(db, ids)}


@router.post("/retention", dependencies=[Depends(authorize)])
def retention(body: Retention, db: Session = Depends(get_db)):
    cutoff = datetime.now(UTC) - timedelta(days=body.days)
    ids = list(db.scalars(select(ConversationSession.id).where(ConversationSession.updated_at < cutoff)))
    return {"sessions_deleted": delete_sessions(db, ids)}
