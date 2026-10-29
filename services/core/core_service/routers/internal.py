"""Service-to-service endpoints used by the agent layer.

Every route here requires a **service** token, never a customer token. Two rules:

* They are read-only or explain-only. An agent may describe what the policy would do, but
  it cannot create an application, move money or issue a sanction letter.
* They return the minimum needed to answer a question — no phone, email or raw identifiers.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..errors import NotFoundError, PolicyRejection
from ..models import Document
from ..money import paise_to_rupees, rupees_to_paise
from ..policy import Applicant, build_policy, decide
from ..schemas import DecisionView, DocumentView, EligibilityPreviewRequest
from ..security import Principal, require_service
from ..services import audit
from ..services import customers as customer_service
from ..services import documents as document_service
from ..storage import build_store

router = APIRouter(tags=["internal"], prefix="/internal")


@router.post("/eligibility/preview", response_model=DecisionView)
def preview_eligibility(
    payload: EligibilityPreviewRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: Principal = Depends(require_service),
) -> DecisionView:
    """Run the credit policy for an amount without creating an application."""
    customer = customer_service.get_or_404(db, payload.customer_id)
    policy = build_policy(settings)
    amount_paise = rupees_to_paise(payload.amount_rupees)

    if not policy.min_loan_amount_paise <= amount_paise <= policy.max_loan_amount_paise:
        raise PolicyRejection(
            "Requested amount is outside the permitted range.",
            details={
                "min_rupees": int(paise_to_rupees(policy.min_loan_amount_paise)),
                "max_rupees": int(paise_to_rupees(policy.max_loan_amount_paise)),
            },
        )
    if not policy.min_tenure_months <= payload.tenure_months <= policy.max_tenure_months:
        raise PolicyRejection(
            "Tenure is outside the permitted range.",
            details={
                "min_months": policy.min_tenure_months,
                "max_months": policy.max_tenure_months,
            },
        )

    applicant = Applicant(
        customer_id=customer.id,
        age=customer.age,
        credit_score=customer.credit_score,
        pre_approved_limit_paise=customer.pre_approved_limit_paise,
        verified_income_paise=document_service.verified_monthly_income_paise(db, customer.id),
    )
    decision = decide(policy, applicant, amount_paise, payload.tenure_months)
    audit.record(
        db,
        actor_type="service",
        actor_id="agent",
        action="eligibility.previewed",
        entity_type="customer",
        entity_id=customer.id,
        metadata={"outcome": decision.outcome.value, "policy_version": decision.policy_version},
    )
    return DecisionView(
        outcome=decision.outcome.value,
        reason_codes=[reason.value for reason in decision.reasons],
        emi_paise=decision.emi_paise,
        tenure_months=decision.tenure_months,
        interest_rate_percent=decision.interest_rate_percent,
        policy_version=decision.policy_version,
    )


@router.post("/documents/{document_id}/process", response_model=DocumentView)
def process_document(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: Principal = Depends(require_service),
) -> DocumentView:
    """Extract now instead of waiting for the queue (small uploads, a customer waiting)."""
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    document_service.process_now(
        db, settings=settings, store=build_store(settings), document=document
    )
    return DocumentView(
        document_id=document.id,
        doc_type=document.doc_type,
        status=document.status,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        extraction_confidence=document.extraction_confidence,
        requires_review=document.requires_review,
        verified_income_paise=document.verified_income_paise,
    )


@router.get("/documents/{document_id}", response_model=DocumentView)
def read_document(
    document_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_service),
) -> DocumentView:
    """Verification state for a stored document, for the document agent.

    Service-scoped, so there is no ownership filter — the customer-token route remains the
    only way a customer reads their own document.
    """
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    return DocumentView(
        document_id=document.id,
        doc_type=document.doc_type,
        status=document.status,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        extraction_confidence=document.extraction_confidence,
        requires_review=document.requires_review,
        verified_income_paise=document.verified_income_paise,
    )


@router.get("/customers/{customer_id}/summary")
def customer_summary(
    customer_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_service),
) -> dict:
    """Facts an agent may use when explaining a decision. No contact details."""
    customer = customer_service.get_or_404(db, customer_id)
    return {
        "customer_id": customer.id,
        "name": customer.name,
        "age": customer.age,
        "city": customer.city,
        "credit_score_band": customer_service.credit_score_band(customer.credit_score),
        "pre_approved_limit_paise": customer.pre_approved_limit_paise,
        "limit_source": customer.limit_source,
        "declared_salary_paise": customer.declared_salary_paise,
        "verified_income_paise": document_service.verified_monthly_income_paise(db, customer.id),
    }
