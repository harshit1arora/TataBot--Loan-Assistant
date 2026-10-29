"""Persistence model.

Money is stored as integer paise everywhere. Every mutation that matters for audit is
written to audit_events, which has no update or delete path in the application.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int] = mapped_column(Integer)
    city: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(160))
    pre_approved_limit_paise: Mapped[int] = mapped_column(Integer)
    declared_salary_paise: Mapped[int] = mapped_column(Integer)
    credit_score: Mapped[int] = mapped_column(Integer)
    # Where the numbers came from. A seeded demo customer has an offered limit and a
    # bureau-style score; a self-registered customer declares their own score and gets
    # an indicative limit derived from declared income. Both are recorded so a decision
    # can always say which it used.
    source: Mapped[str] = mapped_column(String(20), default="seeded")
    score_source: Mapped[str] = mapped_column(String(20), default="demo_seed")
    limit_source: Mapped[str] = mapped_column(String(20), default="offered")
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    address_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    applications: Mapped[list[Application]] = relationship(back_populates="customer")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    requested_amount_paise: Mapped[int] = mapped_column(Integer)
    tenure_months: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="submitted", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="applications")
    decisions: Mapped[list[DecisionRecord]] = relationship(
        back_populates="application", order_by="DecisionRecord.created_at"
    )
    documents: Mapped[list[Document]] = relationship(back_populates="application")

    __table_args__ = (Index("ix_applications_customer_created", "customer_id", "created_at"),)


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(24))
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    emi_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(32))
    interest_rate_percent: Mapped[float] = mapped_column(Integer)
    tenure_months: Mapped[int] = mapped_column(Integer)
    inputs_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application] = relationship(back_populates="decisions")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="stored", index=True)
    extracted_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(nullable=True)
    verified_income_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application | None] = relationship(back_populates="documents")

    __table_args__ = (
        # One sanction letter per application: makes sanction generation idempotent.
        UniqueConstraint("application_id", "doc_type", name="uq_document_app_type"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor_type: Mapped[str] = mapped_column(String(16))  # customer | service | system
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str] = mapped_column(String(64), default="-")
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SupportMessage(Base):
    """A "contact us" message. Stored, referenceable, and readable by its owner."""

    __tablename__ = "support_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    contact: Mapped[str] = mapped_column(String(160))  # phone or email, as given
    topic: Mapped[str] = mapped_column(String(48), default="general")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    request_id: Mapped[str] = mapped_column(String(64), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(120))
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    response_body: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
