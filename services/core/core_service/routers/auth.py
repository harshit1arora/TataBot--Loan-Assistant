"""Token issuance. No endpoint here trusts a caller-supplied identity beyond this point."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..errors import AuthenticationError, NotFoundError
from ..models import Customer
from ..ratelimit import enforce
from ..schemas import ServiceTokenRequest, TokenRequest, TokenResponse
from ..security import (
    issue_customer_token,
    issue_service_token,
    verify_service_credentials,
)
from ..services import audit, kyc

router = APIRouter(tags=["auth"], prefix="/auth")


@router.post("/token", response_model=TokenResponse)
def customer_token(
    payload: TokenRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Exchange a customer id + registered phone for a short-lived access token.

    In production this is the last step of an OTP flow; the demo provider compares the
    phone against the record instead of sending a code, and is disabled in production.
    """
    enforce(request, settings)
    if settings.is_production:
        raise AuthenticationError("Passwordless demo login is disabled.")

    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")

    result = kyc.authenticate(db, customer, payload.phone, kyc.DemoKycProvider())
    if not result.phone_verified:
        audit.record(
            db,
            actor_type="customer",
            actor_id=customer.id,
            action="auth.failed",
            entity_type="customer",
            entity_id=customer.id,
            metadata={"reason": "phone_mismatch"},
        )
        raise AuthenticationError("Phone number does not match our records.")

    token, ttl = issue_customer_token(customer.id, settings)
    audit.record(
        db,
        actor_type="customer",
        actor_id=customer.id,
        action="auth.token_issued",
        entity_type="customer",
        entity_id=customer.id,
        metadata={"scope": "customer"},
    )
    return TokenResponse(access_token=token, expires_in=ttl, scope="customer")


@router.post("/service-token", response_model=TokenResponse)
def service_token(
    payload: ServiceTokenRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    enforce(request, settings)
    verify_service_credentials(payload.client_id, payload.client_secret, settings)
    token, ttl = issue_service_token(payload.client_id, settings)
    return TokenResponse(access_token=token, expires_in=ttl, scope="service")
