"""Underwriter queue. Reviewer identities are separate from customer and service tokens."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import (
    Application,
    BankCrossCheck,
    CustomerNotice,
    Document,
    ReviewAssignment,
    ReviewRecord,
    PrivacyRequest,
)
from ..services import audit, notifications, underwriting
from ..storage import build_store
from .applications import _application_view
from .identity import identity

router = APIRouter(prefix="/v1/reviews")


def reviewer(claims: dict = Depends(identity)) -> str:
    allowed = os.environ.get("OIDC_REVIEWER_SUBJECTS", "").split(",")
    if not claims["sub"] or claims["sub"] not in allowed:
        raise HTTPException(403, "Underwriter role required.")
    return claims["sub"]


class Resolution(BaseModel):
    action: Literal["confirm", "correct", "replace"]
    income_rupees: Annotated[int | None, Field(ge=1, le=10_000_000)] = None
    reason: Annotated[str, Field(min_length=3, max_length=500)]


def pending(db: Session):
    return (
        select(Document)
        .join(Application)
        .where(
            ~select(PrivacyRequest.customer_id).where(PrivacyRequest.customer_id == Document.customer_id).exists(),
            Document.requires_review.is_(True),
            Document.doc_type == "salary_slip",
            Application.status == "document_required",
        )
    )


def bank_summary(db: Session, doc: Document) -> dict | None:
    from .bank_statement import result

    check = db.get(BankCrossCheck, doc.application_id) if doc.application_id else None
    if not check:
        return None
    income = doc.verified_income_paise or (doc.extracted_fields or {}).get("monthly_income_paise")
    return result(check, income)


@router.get("")
def queue(_: str = Depends(reviewer), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "document_id": doc.id,
            "application_id": doc.application_id,
            "filename": doc.original_filename,
            "bank_check": bank_summary(db, doc),
            "confidence": doc.extraction_confidence,
            "fields": doc.extracted_fields,
            "owner": (
                assignment.owner if (assignment := db.get(ReviewAssignment, doc.id)) else None
            ),
            "waiting_since": doc.created_at,
            "overdue": (datetime.now(UTC) - doc.created_at.replace(tzinfo=UTC)).total_seconds()
            >= int(os.getenv("REVIEW_ESCALATION_SECONDS", "86400")),
            "referral": "Income extraction requires human verification",
        }
        for doc in db.scalars(pending(db).order_by(Document.created_at).limit(100))
    ]


@router.post("/{document_id}/claim")
def claim(document_id: str, actor: str = Depends(reviewer), db: Session = Depends(get_db)) -> dict:
    doc = db.scalar(pending(db).where(Document.id == document_id).with_for_update())
    if not doc:
        raise HTTPException(409, "Review is no longer pending.")
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(ReviewAssignment)
        .values(document_id=document_id, owner=actor, assigned_at=datetime.now(UTC))
        .on_conflict_do_nothing(index_elements=["document_id"])
    )
    assignment = db.get(ReviewAssignment, document_id)
    if not assignment or assignment.owner != actor:
        raise HTTPException(409, "Review is assigned to another underwriter.")
    return {"owner": actor}


@router.get("/{document_id}/file")
def file(
    document_id: str,
    _: str = Depends(reviewer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    doc = db.scalar(pending(db).where(Document.id == document_id))
    if not doc:
        raise HTTPException(404, "Pending document missing.")
    return Response(
        build_store(settings).read(doc.storage_key),
        media_type=doc.content_type,
        headers={"Cache-Control": "no-store", "Content-Disposition": "attachment"},
    )


@router.post("/{document_id}")
def resolve(
    document_id: str,
    body: Resolution,
    actor: str = Depends(reviewer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    doc = db.scalar(pending(db).where(Document.id == document_id))
    if not doc or not doc.application_id:
        raise HTTPException(409, "Review is no longer pending.")
    locked = db.scalar(
        update(Application)
        .where(Application.id == doc.application_id, Application.status == "document_required")
        .values(status=Application.status)
        .returning(Application.id)
    )
    if not locked:
        raise HTTPException(409, "Review is no longer pending.")
    db.expire(doc)
    doc = db.scalar(pending(db).where(Document.id == document_id).with_for_update())
    if not doc or not doc.application_id:
        raise HTTPException(409, "Review is no longer pending.")
    application = db.get(Application, doc.application_id)
    if not application:
        raise HTTPException(404, "Application missing.")
    assignment = db.get(ReviewAssignment, document_id)
    if assignment and assignment.owner != actor:
        raise HTTPException(409, "Review is assigned to another underwriter.")
    income = None
    if body.action == "confirm":
        income = (doc.extracted_fields or {}).get("monthly_income_paise")
    if body.action == "correct" and body.income_rupees:
        income = body.income_rupees * 100
    if body.action != "replace" and (not isinstance(income, int) or income <= 0):
        raise HTTPException(422, "Supply a corrected monthly income or request replacement.")
    check = db.get(BankCrossCheck, application.id)
    if check and body.action != "replace" and any(value != income for value in check.credits_paise):
        raise HTTPException(
            409,
            "Salary credits do not match the reviewed income. Request replacement or correct the statement.",
        )
    claimed = db.scalar(
        update(Document)
        .where(Document.id == doc.id, Document.requires_review.is_(True))
        .values(requires_review=False)
        .returning(Document.id)
    )
    if not claimed:
        raise HTTPException(409, "Another reviewer completed the review.")
    db.add(
        ReviewRecord(
            document_id=doc.id,
            application_id=application.id,
            reviewer=actor,
            action=body.action,
            reason=body.reason,
            income_paise=income,
        )
    )
    doc.verified_income_paise = income
    if body.action == "replace":
        doc.status = "replacement_requested"
        doc.application_id = None  # the review retains the link; a replacement can now be uploaded
    else:
        doc.status = "extracted"
        db.flush()
        underwriting.evaluate(db, settings=settings, application=application, reviewed=doc)
    notice = CustomerNotice(
        customer_id=application.customer_id,
        application_id=application.id,
        message="A replacement salary slip is required."
        if body.action == "replace"
        else f"Your application decision is {application.status.replace(chr(95), chr(32))}.",
    )
    db.add(notice)
    db.flush()
    notifications.schedule_notice(db, notice)
    audit.record(
        db,
        actor_type="underwriter",
        actor_id=hashlib.sha256(actor.encode()).hexdigest(),
        action="document.reviewed",
        entity_type="document",
        entity_id=doc.id,
        metadata={"action": body.action, "application_id": application.id},
    )
    return {"application": _application_view(db, application), "action": body.action}
