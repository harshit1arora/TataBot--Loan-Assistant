"""Transactional notification queue and retrying email delivery."""

from __future__ import annotations

import os
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Application, Customer, CustomerNotice, Delivery, Document


def enqueue(db: Session, key: str, category: str, recipient: str, subject: str, body: str) -> None:
    if not recipient:
        return
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(Delivery)
        .values(
            event_key=key,
            category=category,
            recipient=recipient,
            subject=subject,
            body=body,
            status="pending",
            attempts=0,
            next_attempt_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["event_key"])
    )


def schedule_notice(db: Session, notice: CustomerNotice) -> None:
    customer = db.get(Customer, notice.customer_id)
    if customer and customer.email:
        enqueue(
            db,
            "notice:" + notice.id,
            "customer",
            customer.email,
            "Your TataBot application has an update",
            "Your application has an update. Sign in to TataBot to view the details.",
        )


def schedule_escalations(db: Session) -> None:
    recipient = os.getenv("ESCALATION_EMAIL", "").strip()
    if not recipient:
        return
    threshold = datetime.now(UTC) - timedelta(
        seconds=int(os.getenv("REVIEW_ESCALATION_SECONDS", "86400"))
    )
    rows = db.execute(
        select(Document.id)
        .join(Application)
        .where(
            Document.requires_review.is_(True),
            Document.doc_type == "salary_slip",
            Application.status == "document_required",
            Document.created_at <= threshold,
        )
    )
    for (document_id,) in rows:
        enqueue(
            db,
            "review:" + document_id,
            "escalation",
            recipient,
            "TataBot review is overdue",
            "A document review is overdue. Sign in to the underwriter queue.",
        )


def deliver_once() -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip()
    if not host or not sender:
        return False
    now = datetime.now(UTC)
    with session_scope() as db:
        candidate = db.scalar(
            select(Delivery.id)
            .where(
                Delivery.next_attempt_at <= now,
                or_(
                    Delivery.status == "pending",
                    (Delivery.status == "sending") & (Delivery.lease_until < now),
                ),
            )
            .order_by(Delivery.created_at)
            .limit(1)
        )
        if not candidate:
            return False
        claimed = db.scalar(
            update(Delivery)
            .where(
                Delivery.id == candidate,
                Delivery.next_attempt_at <= now,
                or_(
                    Delivery.status == "pending",
                    (Delivery.status == "sending") & (Delivery.lease_until < now),
                ),
            )
            .values(
                status="sending",
                lease_until=now + timedelta(minutes=2),
                attempts=Delivery.attempts + 1,
            )
            .returning(Delivery.id)
        )
        if not claimed:
            return True
    with session_scope() as db:
        item = db.get(Delivery, candidate)
        if not item:
            return True
        if item.category == "escalation":
            doc = db.get(Document, item.event_key.removeprefix("review:"))
            if not doc or not doc.requires_review:
                item.status = "cancelled"
                return True
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = sender, item.recipient, item.subject
        message["Message-ID"] = f"<{item.id}@tatabot.local>"
        message.set_content(item.body)
        try:
            with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
                if os.getenv("SMTP_STARTTLS", "true").lower() == "true":
                    smtp.starttls()
                username = os.getenv("SMTP_USERNAME", "")
                if username:
                    smtp.login(username, os.environ["SMTP_PASSWORD"])
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException, KeyError, ValueError) as exc:
            item.last_error = type(exc).__name__
            item.status = (
                "pending" if item.attempts < int(os.getenv("SMTP_MAX_ATTEMPTS", "8")) else "failed"
            )
            item.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 30 * 2 ** min(item.attempts, 7))
            )
            item.lease_until = None
            return True
        item.status = "sent"
        item.sent_at = datetime.now(UTC)
        item.lease_until = None
        item.last_error = None
        return True
