from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..ratelimit import enforce
from ..schemas import CustomerProfile, RegisterCustomerRequest, RegisterCustomerResponse
from ..security import Principal, require_customer
from ..services import customers as customer_service
from ..services import onboarding

router = APIRouter(tags=["customers"])


def _profile(customer) -> CustomerProfile:
    return CustomerProfile(
        customer_id=customer.id,
        name=customer.name,
        city=customer.city,
        pre_approved_limit_paise=customer.pre_approved_limit_paise,
        limit_source=customer.limit_source,
        credit_score_band=customer_service.credit_score_band(customer.credit_score),
        score_source=customer.score_source,
        phone_verified=customer.phone_verified,
        address_verified=customer.address_verified,
    )


@router.get("/v1/customers/me", response_model=CustomerProfile)
def read_me(
    db: Session = Depends(get_db), principal: Principal = Depends(require_customer)
) -> CustomerProfile:
    """The customer can only ever read their own profile — the id comes from the token."""
    return _profile(customer_service.get_or_404(db, principal.customer_id))


@router.post("/v1/customers", response_model=RegisterCustomerResponse, status_code=201)
def register_customer(
    payload: RegisterCustomerRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegisterCustomerResponse:
    """Self-service signup — a new customer, not one of the seeded demo set."""
    enforce(request, settings)
    customer = onboarding.register(
        db,
        settings=settings,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        age=payload.age,
        city=payload.city,
        declared_monthly_income_rupees=payload.declared_monthly_income_rupees,
        declared_credit_score=payload.declared_credit_score,
    )
    return RegisterCustomerResponse(
        customer_id=customer.id,
        profile=_profile(customer),
        next_step="Sign in with this mobile number to start an application.",
    )
