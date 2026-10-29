"""Contact-us endpoints.

POST is open (a person may need help before they can sign in) but rate-limited and
length-capped; GET returns only the signed-in customer's own tickets.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..logging_setup import request_id_var
from ..ratelimit import enforce
from ..schemas import (
    SupportMessageCreated,
    SupportMessageRequest,
    SupportMessageView,
)
from ..security import Principal, get_principal, require_customer
from ..services import support as support_service

router = APIRouter(tags=["support"], prefix="/v1/support")

EXPECTED_RESPONSE = "within one working day"


@router.post("/messages", response_model=SupportMessageCreated, status_code=201)
def create_message(
    payload: SupportMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SupportMessageCreated:
    enforce(request, settings)

    # Attach the ticket to the customer when a token is present, but do not require one.
    customer_id: str | None = None
    try:
        principal: Principal = get_principal(request, settings)
        if principal.scope == "customer":
            customer_id = principal.subject
    except Exception:  # noqa: BLE001 - anonymous contact is a supported path
        customer_id = None

    record = support_service.create(
        db,
        customer_id=customer_id,
        name=payload.name,
        contact=payload.contact,
        topic=payload.topic,
        message=payload.message,
        request_id=request_id_var.get(),
    )
    return SupportMessageCreated(
        reference=record.reference, status=record.status, expected_response=EXPECTED_RESPONSE
    )


@router.get("/messages", response_model=list[SupportMessageView])
def list_messages(
    db: Session = Depends(get_db), principal: Principal = Depends(require_customer)
) -> list[SupportMessageView]:
    rows = support_service.list_for_customer(db, principal.customer_id)
    return [
        SupportMessageView(
            reference=row.reference,
            topic=row.topic,
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]
