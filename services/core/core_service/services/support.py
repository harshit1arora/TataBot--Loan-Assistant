"""Contact-us messages.

Stored rather than emailed, so the reference a customer is shown actually resolves to
something a support team can read. Nothing here is fire-and-forget.
"""
from __future__ import annotations

import secrets
from string import ascii_uppercase, digits

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SupportMessage
from ..services import audit

TOPICS = {"general", "application", "document", "repayment", "grievance"}


def _reference() -> str:
    body = "".join(secrets.choice(ascii_uppercase + digits) for _ in range(6))
    return f"SUP-{body}"


def create(
    db: Session,
    *,
    customer_id: str | None,
    name: str,
    contact: str,
    topic: str,
    message: str,
    request_id: str = "-",
) -> SupportMessage:
    topic = topic if topic in TOPICS else "general"
    record = SupportMessage(
        reference=_reference(),
        customer_id=customer_id,
        name=name.strip()[:120],
        contact=contact.strip()[:160],
        topic=topic,
        message=message.strip()[:2000],
        request_id=request_id,
    )
    db.add(record)
    db.flush()
    audit.record(
        db,
        actor_type="customer" if customer_id else "anonymous",
        actor_id=customer_id or "anonymous",
        action="support.message_created",
        entity_type="support_message",
        entity_id=record.id,
        metadata={"reference": record.reference, "topic": topic},
    )
    return record


def list_for_customer(db: Session, customer_id: str, limit: int = 20) -> list[SupportMessage]:
    return list(
        db.execute(
            select(SupportMessage)
            .where(SupportMessage.customer_id == customer_id)
            .order_by(SupportMessage.created_at.desc())
            .limit(limit)
        ).scalars()
    )
