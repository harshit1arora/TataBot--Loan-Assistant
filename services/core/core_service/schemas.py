"""Request/response contracts. One vocabulary: snake_case, *_paise integers, stable codes."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- auth -----------------------------------------------------------------
class TokenRequest(StrictModel):
    customer_id: Annotated[str, Field(pattern=r"^CUST\d{3}$")]
    phone: Annotated[str, Field(pattern=r"^[6-9]\d{9}$")]


class ServiceTokenRequest(StrictModel):
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - a media type, not a secret
    expires_in: int
    scope: Literal["customer", "service"]


# --- customer -------------------------------------------------------------
class CustomerProfile(BaseModel):
    """What the customer (or the conversation service) is allowed to see."""

    customer_id: str
    name: str
    city: str
    pre_approved_limit_paise: int
    limit_source: Literal["offered", "indicative"]
    credit_score_band: Literal["excellent", "good", "fair"]
    score_source: Literal["demo_seed", "self_declared", "bureau"]
    phone_verified: bool
    address_verified: bool


class RegisterCustomerRequest(StrictModel):
    """Self-service signup. The applicant supplies their own details.

    `declared_credit_score` is labelled "declared" on purpose: there is no bureau pull in
    this build, so the value is taken at face value and recorded as self-declared.
    """

    name: Annotated[str, Field(min_length=2, max_length=120)]
    phone: Annotated[str, Field(pattern=r"^[6-9]\d{9}$")]
    email: Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")]
    age: Annotated[int, Field(ge=18, le=80)]
    city: Annotated[str, Field(min_length=2, max_length=80)]
    declared_monthly_income_rupees: Annotated[int, Field(ge=5_000, le=10_000_000)]
    declared_credit_score: Annotated[int, Field(ge=300, le=900)]


class RegisterCustomerResponse(BaseModel):
    customer_id: str
    profile: CustomerProfile
    next_step: str


class SupportMessageRequest(StrictModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    contact: Annotated[str, Field(min_length=5, max_length=160)]
    topic: Literal["general", "application", "document", "repayment", "grievance"] = "general"
    message: Annotated[str, Field(min_length=10, max_length=2000)]


class SupportMessageView(BaseModel):
    reference: str
    topic: str
    status: str
    created_at: datetime


class SupportMessageCreated(BaseModel):
    reference: str
    status: str
    expected_response: str


# --- applications ---------------------------------------------------------
class CreateApplicationRequest(StrictModel):
    requested_amount_rupees: Annotated[int, Field(ge=1, le=100_000_000)]
    tenure_months: Annotated[int, Field(ge=1, le=120)]


class DecisionView(BaseModel):
    outcome: Literal["approve", "reject", "require_document"]
    reason_codes: list[str]
    emi_paise: int | None = None
    tenure_months: int
    interest_rate_percent: float
    policy_version: str


class EligibilityPreviewRequest(StrictModel):
    """Read-only eligibility check for the agent layer. Creates nothing."""

    customer_id: Annotated[str, Field(pattern=r"^CUST\d{3,}$")]
    amount_rupees: Annotated[int, Field(ge=1, le=100_000_000)]
    tenure_months: Annotated[int, Field(ge=1, le=120)]


class ApplicationView(BaseModel):
    application_id: str
    customer_id: str
    requested_amount_paise: int
    tenure_months: int
    status: str
    decision: DecisionView | None = None
    sanction_document_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationStatusView(BaseModel):
    application_id: str
    status: str
    stage: Literal[
        "submitted", "document_required", "approved", "rejected", "sanctioned"
    ]
    decision: DecisionView | None = None
    sanction_document_id: str | None = None
    next_steps: list[str] = []


# --- documents ------------------------------------------------------------
class DocumentView(BaseModel):
    document_id: str
    doc_type: str
    status: str
    content_type: str
    size_bytes: int
    extraction_confidence: float | None = None
    requires_review: bool = False
    verified_income_paise: int | None = None


class SignedUrlResponse(BaseModel):
    url: str
    expires_in: int


# --- misc -----------------------------------------------------------------
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    checks: dict[str, str]
    time: datetime


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: object | None = None
