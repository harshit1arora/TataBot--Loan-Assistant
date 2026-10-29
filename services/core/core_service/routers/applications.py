"""Application endpoints. Every route resolves the customer from the token."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import idempotency
from ..config import Settings, get_settings
from ..db import get_db
from ..errors import ConflictError
from ..models import Application
from ..ratelimit import enforce
from ..schemas import (
    ApplicationStatusView,
    ApplicationView,
    CreateApplicationRequest,
    DecisionView,
    DocumentView,
)
from ..security import Principal, require_customer
from ..services import documents as document_service
from ..services import sanction as sanction_service
from ..services import underwriting
from ..storage import build_store

router = APIRouter(tags=["applications"], prefix="/v1/applications")


def _decision_view(record) -> DecisionView | None:
    if record is None:
        return None
    return DecisionView(
        outcome=record.outcome,
        reason_codes=list(record.reason_codes or []),
        emi_paise=record.emi_paise,
        tenure_months=record.tenure_months,
        interest_rate_percent=float(record.interest_rate_percent),
        policy_version=record.policy_version,
    )


def _application_view(db: Session, application: Application) -> ApplicationView:
    letter = document_service.sanction_letter_for(db, application.id)
    return ApplicationView(
        application_id=application.id,
        customer_id=application.customer_id,
        requested_amount_paise=application.requested_amount_paise,
        tenure_months=application.tenure_months,
        status=application.status,
        decision=_decision_view(underwriting.latest_decision(db, application.id)),
        sanction_document_id=letter.id if letter else None,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


@router.post("", response_model=ApplicationView, status_code=201)
def create_application(
    payload: CreateApplicationRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_customer),
) -> ApplicationView:
    """Create an application and run the credit policy against it in one step."""
    enforce(request, settings)
    endpoint = "POST /v1/applications"
    if idempotency_key:
        cached = idempotency.lookup(db, idempotency_key, endpoint, principal.customer_id)
        if cached is not None:
            return ApplicationView.model_validate(cached)

    application = underwriting.create_application(
        db,
        settings=settings,
        customer_id=principal.customer_id,
        requested_amount_rupees=payload.requested_amount_rupees,
        tenure_months=payload.tenure_months,
    )
    underwriting.evaluate(db, settings=settings, application=application)
    view = _application_view(db, application)
    if idempotency_key:
        idempotency.store(
            db, idempotency_key, endpoint, principal.customer_id, view.model_dump(mode="json")
        )
    return view


@router.get("", response_model=list[ApplicationView])
def list_applications(
    db: Session = Depends(get_db), principal: Principal = Depends(require_customer)
) -> list[ApplicationView]:
    rows = db.execute(
        select(Application)
        .where(Application.customer_id == principal.customer_id)
        .order_by(Application.created_at.desc())
        .limit(50)
    ).scalars().all()
    return [_application_view(db, row) for row in rows]


@router.get("/{application_id}", response_model=ApplicationView)
def read_application(
    application_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer),
) -> ApplicationView:
    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    return _application_view(db, application)


@router.get("/{application_id}/status", response_model=ApplicationStatusView)
def application_status(
    application_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer),
) -> ApplicationStatusView:
    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    letter = document_service.sanction_letter_for(db, application.id)
    next_steps = {
        "submitted": ["Your application is being assessed."],
        "document_required": ["Upload your latest salary slip to continue."],
        "approved": ["Download your sanction letter."],
        "rejected": ["Review the reason codes, or apply again after six months."],
        "sanctioned": ["Your sanction letter is ready to download."],
    }.get(application.status, [])
    stage: Literal[
        "submitted", "document_required", "approved", "rejected", "sanctioned"
    ] = application.status  # type: ignore[assignment]  # constrained by the model's states
    return ApplicationStatusView(
        application_id=application.id,
        status=application.status,
        stage=stage,
        decision=_decision_view(underwriting.latest_decision(db, application.id)),
        sanction_document_id=letter.id if letter else None,
        next_steps=next_steps,
    )


@router.post("/{application_id}/evaluate", response_model=ApplicationView)
def re_evaluate(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_customer),
) -> ApplicationView:
    """Re-run the policy after new information (a document) arrived.

    Only an application that is waiting on a document can be re-evaluated, so this
    cannot be used to grind a rejected application through the engine.
    """
    enforce(request, settings)
    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    if application.status != "document_required":
        raise ConflictError(
            "Only an application awaiting a document can be re-evaluated.",
            details={"status": application.status},
        )
    underwriting.evaluate(db, settings=settings, application=application)
    return _application_view(db, application)


@router.post("/{application_id}/sanction", response_model=DocumentView)
def issue_sanction(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_customer),
) -> DocumentView:
    enforce(request, settings)
    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    if application.status == "rejected":
        raise ConflictError("A rejected application cannot be sanctioned.")
    letter = sanction_service.generate(
        db, settings=settings, store=build_store(settings), application=application
    )
    return DocumentView(
        document_id=letter.id,
        doc_type=letter.doc_type,
        status=letter.status,
        content_type=letter.content_type,
        size_bytes=letter.size_bytes,
    )
