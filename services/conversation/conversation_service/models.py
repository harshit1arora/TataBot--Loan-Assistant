"""Conversation state.

The workflow state lives here, keyed by session, and is only ever advanced by the
orchestrator. Nothing the client sends can name a state.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(32), default="new")
    application_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requested_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tenure_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)  # optimistic concurrency
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    messages: Mapped[list[Message]] = relationship(
        back_populates="session", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("conversation_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # customer | assistant | system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ConversationSession] = relationship(back_populates="messages")


class Transition(Base):
    """Every state change, with the event that caused it. This is the audit of the flow."""

    __tablename__ = "transitions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("conversation_sessions.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    event: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
