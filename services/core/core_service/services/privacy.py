"""Retryable, scoped customer erasure and opt-in retention operations."""
import os
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, or_, select

from ..config import get_settings
from ..db import session_scope
from ..models import (Application, AuditEvent, BankCrossCheck, Customer, CustomerNotice,
                      DecisionRecord, Delivery, Document, ExtractionJob, IdempotencyRecord,
                      PilotQuote, PrivacyRequest, ReviewAssignment, ReviewRecord,
                      ShadowPrediction, SupportAssignment, SupportMessage, VerifiedIdentity)
from ..storage import build_store


def _conversation(path: str, body: dict) -> None:
    url = os.getenv("CONVERSATION_BASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("CONVERSATION_BASE_URL is not configured")
    response = httpx.post(url + "/internal/privacy/" + path, json=body,
                          headers={"X-Privacy-Secret": get_settings().service_client_secret}, timeout=15)
    response.raise_for_status()


def erase_one(customer_id: str) -> None:
    # Do not hold a core write transaction across a network call; either side can retry.
    _conversation("erase", {"customer_id": customer_id})
    settings = get_settings()
    store = build_store(settings)
    with session_scope() as db:
        row = db.get(PrivacyRequest, customer_id)
        if not row or row.status != "erasure_pending":
            return
        docs = list(db.scalars(select(Document).where(Document.customer_id == customer_id)))
        for doc in docs:
            store.delete(doc.storage_key)
        app_ids = list(db.scalars(select(Application.id).where(Application.customer_id == customer_id)))
        doc_ids = [d.id for d in docs]
        decision_ids = list(db.scalars(select(DecisionRecord.id).where(DecisionRecord.application_id.in_(app_ids))))
        support_ids = list(db.scalars(select(SupportMessage.id).where(SupportMessage.customer_id == customer_id)))
        notice_ids = list(db.scalars(select(CustomerNotice.id).where(CustomerNotice.customer_id == customer_id)))
        quote_ids = list(db.scalars(select(PilotQuote.id).where(PilotQuote.customer_id == customer_id)))
        db.execute(delete(Delivery).where(Delivery.event_key.in_(["notice:" + i for i in notice_ids] + ["review:" + i for i in doc_ids])))
        db.execute(delete(ShadowPrediction).where(ShadowPrediction.decision_id.in_(decision_ids)))
        db.execute(delete(CustomerNotice).where(CustomerNotice.customer_id == customer_id))
        db.execute(delete(BankCrossCheck).where(BankCrossCheck.customer_id == customer_id))
        db.execute(delete(ReviewRecord).where(ReviewRecord.document_id.in_(doc_ids)))
        db.execute(delete(ReviewAssignment).where(ReviewAssignment.document_id.in_(doc_ids)))
        db.execute(delete(ExtractionJob).where(ExtractionJob.document_id.in_(doc_ids)))
        db.execute(delete(Document).where(Document.id.in_(doc_ids)))
        db.execute(delete(PilotQuote).where(PilotQuote.customer_id == customer_id))
        db.execute(delete(DecisionRecord).where(DecisionRecord.id.in_(decision_ids)))
        db.execute(delete(Application).where(Application.id.in_(app_ids)))
        db.execute(delete(SupportAssignment).where(SupportAssignment.message_id.in_(support_ids)))
        db.execute(delete(SupportMessage).where(SupportMessage.id.in_(support_ids)))
        db.execute(delete(VerifiedIdentity).where(VerifiedIdentity.customer_id == customer_id))
        db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.customer_id == customer_id))
        ids = [customer_id, *app_ids, *doc_ids, *decision_ids, *support_ids, *notice_ids, *quote_ids]
        db.execute(delete(AuditEvent).where(or_(AuditEvent.actor_id == customer_id, AuditEvent.entity_id.in_(ids))))
        db.execute(delete(Customer).where(Customer.id == customer_id))
        row.status = "local_erased"
        row.last_error = None


def process_pending() -> int:
    with session_scope() as db:
        ids = list(db.scalars(select(PrivacyRequest.customer_id).where(PrivacyRequest.status == "erasure_pending")))
    done = 0
    for customer_id in ids:
        try:
            erase_one(customer_id)
            done += 1
        except Exception as exc:
            with session_scope() as db:
                row = db.get(PrivacyRequest, customer_id)
                if row and row.status == "erasure_pending":
                    row.last_error = type(exc).__name__
    return done


def run_retention() -> None:
    support_days = os.getenv("SUPPORT_RETENTION_DAYS", "").strip()
    if support_days:
        days = int(support_days)
        if days <= 0:
            raise ValueError("SUPPORT_RETENTION_DAYS must be positive")
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with session_scope() as db:
            ids = list(db.scalars(select(SupportMessage.id).where(
                SupportMessage.status == "closed", SupportMessage.closed_at < cutoff)))
            db.execute(delete(SupportAssignment).where(SupportAssignment.message_id.in_(ids)))
            db.execute(delete(AuditEvent).where(AuditEvent.entity_type == "support_message", AuditEvent.entity_id.in_(ids)))
            db.execute(delete(SupportMessage).where(SupportMessage.id.in_(ids)))
    value = os.getenv("CONVERSATION_RETENTION_DAYS", "").strip()
    if value:
        days = int(value)
        if days <= 0:
            raise ValueError("CONVERSATION_RETENTION_DAYS must be positive")
        _conversation("retention", {"days": days})
