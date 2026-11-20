"""Customer-owned, expiring policy quotes and atomic application acceptance."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Customer, PilotQuote, ReviewRecord, VerifiedIdentity
from ..money import compute_emi_paise
from ..policy import Applicant, build_policy, decide
from ..security import Principal, require_customer
from ..services import documents, underwriting
from ..storage import build_store
from .applications import _application_view

router = APIRouter(prefix="/v1")


class Scenario(BaseModel):
    amount_rupees: Annotated[int, Field(gt=0, le=5_000_000)]
    tenure_months: Annotated[int, Field(gt=0, le=60)]


class ProductEstimate(Scenario):
    product: Annotated[str, Field(min_length=1, max_length=80)]
    rate: Annotated[float, Field(gt=0, lt=100)]


class Comparison(BaseModel):
    scenarios: Annotated[list[Scenario], Field(min_length=1, max_length=3)]


def terms(db: Session, settings: Settings, customer: Customer, scenario: Scenario) -> dict:
    policy = build_policy(settings)
    amount = scenario.amount_rupees * 100
    months = scenario.tenure_months
    if not (
        policy.min_loan_amount_paise <= amount <= policy.max_loan_amount_paise
        and policy.min_tenure_months <= months <= policy.max_tenure_months
    ):
        raise HTTPException(422, "Scenario outside the configured lending range.")
    income = documents.verified_monthly_income_paise(db, customer.id)
    applicant = Applicant(
        customer_id=customer.id,
        age=customer.age,
        credit_score=customer.credit_score,
        pre_approved_limit_paise=customer.pre_approved_limit_paise,
        verified_income_paise=income,
    )
    decision = decide(policy, applicant, amount, months)
    emi = compute_emi_paise(amount, policy.annual_rate_percent, months)
    return {
        **scenario.model_dump(),
        "rate": policy.annual_rate_percent,
        "emi_paise": emi,
        "total_interest_paise": emi * months - amount,
        "policy_version": policy.version,
        "product": "Core personal loan",
        "outcome": decision.outcome.value,
        "reasons": [reason.value for reason in decision.reasons],
        "income_source": "verified_document" if income else "declared",
        "indicative_limit_paise": customer.pre_approved_limit_paise,
    }


def save_quote(db: Session, owner: str, snapshot: dict) -> PilotQuote:
    row = PilotQuote(customer_id=owner, terms=snapshot, expires_at=int(time.time()) + 900)
    db.add(row)
    db.flush()
    return row


def view(row: PilotQuote) -> dict:
    return {"quote_id": row.id, "expires_at": row.expires_at, **row.terms}


@router.post("/quotes")
def issue(
    scenario: Scenario,
    principal: Principal = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    customer = db.get(Customer, principal.customer_id)
    if not customer:
        raise HTTPException(404, "Customer missing.")
    return view(save_quote(db, customer.id, terms(db, settings, customer, scenario)))


@router.get("/quotes/{quote_id}")
def read(
    quote_id: str, principal: Principal = Depends(require_customer), db: Session = Depends(get_db)
) -> dict:
    row = db.get(PilotQuote, quote_id)
    if not row or row.customer_id != principal.customer_id:
        raise HTTPException(404, "Quote missing.")
    return view(row)


@router.post("/quotes/compare")
def compare(
    payload: Comparison,
    principal: Principal = Depends(require_customer),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> list[dict]:
    customer = db.get(Customer, principal.customer_id)
    if not customer:
        raise HTTPException(404, "Customer missing.")
    return [
        view(save_quote(db, customer.id, terms(db, settings, customer, item)))
        for item in payload.scenarios
    ]


@router.post("/quotes/{quote_id}/accept")
def accept(
    quote_id: str,
    principal: Principal = Depends(require_customer),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict:
    quote = db.get(PilotQuote, quote_id)
    if not quote or quote.customer_id != principal.customer_id:
        raise HTTPException(404, "Quote missing.")
    if quote.application_id:
        application = underwriting.get_owned_application(
            db, quote.application_id, principal.customer_id
        )
        return {"application": _application_view(db, application), "quote_id": quote.id}
    customer = db.get(Customer, principal.customer_id)
    if not customer:
        raise HTTPException(404, "Customer missing.")
    current = terms(db, settings, customer, Scenario(**quote.terms))
    if quote.terms.get("pricing_source") == "OfferMart" and current["rate"] == quote.terms["rate"]:
        current.update(product=quote.terms["product"], pricing_source="OfferMart")
    if current != quote.terms or quote.expires_at <= time.time():
        replacement = save_quote(db, customer.id, current)
        return {
            "confirmation_required": True,
            "previous": view(quote),
            "replacement": view(replacement),
            "reason": "Quote expired"
            if quote.expires_at <= time.time()
            else "Policy or applicant facts changed",
        }
    claimed = db.execute(
        update(PilotQuote)
        .where(PilotQuote.id == quote.id, PilotQuote.accepted.is_(False))
        .values(accepted=True)
        .returning(PilotQuote.id)
    ).scalar_one_or_none()
    if not claimed:
        db.refresh(quote)
        if quote.application_id:
            application = underwriting.get_owned_application(db, quote.application_id, customer.id)
            return {"application": _application_view(db, application), "quote_id": quote.id}
        raise HTTPException(409, "Acceptance in progress.")
    application = underwriting.create_application(
        db,
        settings=settings,
        customer_id=customer.id,
        requested_amount_rupees=current["amount_rupees"],
        tenure_months=current["tenure_months"],
    )
    quote.application_id = application.id
    db.flush()
    underwriting.evaluate(db, settings=settings, application=application)
    return {"application": _application_view(db, application), "quote_id": quote.id}


@router.get("/applications/{application_id}/summary")
def summary(
    application_id: str,
    principal: Principal = Depends(require_customer),
    db: Session = Depends(get_db),
) -> dict:
    from sqlalchemy import select

    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    decision = underwriting.latest_decision(db, application.id)
    quote = db.scalar(select(PilotQuote).where(PilotQuote.application_id == application.id))
    review = db.scalar(
        select(ReviewRecord)
        .where(ReviewRecord.application_id == application.id)
        .order_by(ReviewRecord.created_at.desc())
    )
    identity = db.scalar(
        select(VerifiedIdentity).where(VerifiedIdentity.customer_id == principal.customer_id)
    )
    snapshot = decision.inputs_snapshot if decision else {}
    action = {
        "document_required": "Upload a salary slip",
        "approved": "Request your sanction letter",
        "sanctioned": "Download your sanction letter",
        "rejected": "Read the decision reasons",
    }.get(application.status)
    from ..models import Document

    pending = db.scalar(
        select(Document.id).where(
            Document.application_id == application.id, Document.requires_review.is_(True)
        )
    )
    if pending:
        action = "Await document review"
    elif review and review.action == "replace" and application.status == "document_required":
        action = "Upload a replacement salary slip"
    if decision and "credit_score_below_min" in decision.reason_codes:
        action = (
            "Check the credit score used in this assessment and contact support if it is incorrect."
        )
    explanations = {
        "within_pre_approved_limit": "Within your available limit.",
        "verified_income_document_required": "Verified income is required above your available limit.",
        "emi_within_foir": "The monthly payment fits the verified-income policy.",
        "emi_exceeds_foir_limit": "The monthly payment exceeds the verified-income limit.",
        "credit_score_below_min": "The recorded credit score is below the policy threshold.",
        "age_out_of_range": "Age is outside the policy range.",
        "amount_above_max_multiple_of_pre_approved": "The amount exceeds the policy ceiling for your limit.",
    }
    timeline: list[dict] = [{"at": application.created_at, "event": "Application submitted"}]
    for document in application.documents:
        if document.doc_type == "salary_slip":
            timeline.append({"at": document.created_at, "event": "Salary slip submitted"})
        elif document.doc_type == "sanction_letter":
            timeline.append({"at": document.created_at, "event": "Sanction letter issued"})
    reviews = db.scalars(select(ReviewRecord).where(ReviewRecord.application_id == application.id))
    for item in reviews:
        label = "Replacement salary slip requested" if item.action == "replace" else "Income reviewed"
        timeline.append({"at": item.created_at, "event": label})
    for decision_item in application.decisions:
        timeline.append({"at": decision_item.created_at, "event": "Decision: " + decision_item.outcome.replace("_", " ")})
    timeline.sort(key=lambda item: item["at"].isoformat())
    return {
        "timeline": timeline,
        "reasons": [explanations.get(r, r.replace("_", " ")) for r in decision.reason_codes]
        if decision
        else [],
        "application": _application_view(db, application),
        "quote": view(quote) if quote else None,
        "income_source": snapshot.get("income_source", "declared"),
        "verified_income_paise": snapshot.get("verified_income_paise"),
        "score_source": snapshot.get("score_source", "unknown"),
        "identity_source": identity.issuer if identity else "demo",
        "consent_version": identity.consent_version if identity else None,
        "next_action": action,
    }


@router.post("/applications/{application_id}/documents/{document_id}/assess")
def assess(
    application_id: str,
    document_id: str,
    principal: Principal = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    doc = documents.get_owned(db, document_id, principal.customer_id)
    if doc.application_id != application.id or doc.doc_type != "salary_slip":
        raise HTTPException(404, "Application evidence missing.")
    if application.status == "document_required":
        documents.process_now(db, settings=settings, store=build_store(settings), document=doc)
        if doc.verified_income_paise and not doc.requires_review:
            underwriting.evaluate(db, settings=settings, application=application, reviewed=doc)
    return {
        "application": _application_view(db, application),
        "requires_review": doc.requires_review,
    }



