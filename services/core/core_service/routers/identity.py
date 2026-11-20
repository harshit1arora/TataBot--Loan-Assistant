"""Exchange a verified provider identity for a customer-scoped TataBot session."""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import VerifiedIdentity, PrivacyRequest
from ..ratelimit import enforce
from ..schemas import RegisterCustomerRequest
from ..security import issue_customer_token
from ..services import onboarding

router = APIRouter()
CONSENT = "income-assessment-v1"


@lru_cache
def _keys(uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(uri, timeout=5)


def identity(authorization: str | None = Header(None)) -> dict:
    issuer = os.getenv("OIDC_ISSUER", "")
    uri = os.getenv("OIDC_JWKS_URL", "")
    audience = os.getenv("OIDC_AUDIENCE", "")
    if not issuer.startswith("https://") or not uri.startswith("https://") or not audience:
        raise HTTPException(503, "Configure the identity provider.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Provider bearer token required.")
    token = authorization[7:]
    try:
        signing = _keys(uri).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid provider identity.") from exc


class Enroll(BaseModel):
    profile: RegisterCustomerRequest
    consent_version: str


@router.post("/auth/verified")
def exchange(
    request: Request,
    payload: Enroll | None = None,
    claims: dict = Depends(identity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    enforce(request, settings)
    subject = hashlib.sha256(f"{claims['iss']}\0{claims['sub']}".encode()).hexdigest()
    linked = db.get(VerifiedIdentity, subject)
    if linked is None:
        if not payload or payload.consent_version != CONSENT:
            raise HTTPException(
                422, "A profile and current income-assessment consent are required."
            )
        if (
            claims.get("phone_number_verified") is not True
            or claims.get("phone_number") != "+91" + payload.profile.phone
        ):
            raise HTTPException(
                403, "Verify the registered mobile number with the identity provider."
            )
        customer = onboarding.register(db, settings=settings, **payload.profile.model_dump())
        customer.phone_verified = True
        linked = VerifiedIdentity(
            identity_hash=subject,
            customer_id=customer.id,
            issuer=claims["iss"],
            consent_version=CONSENT,
        )
        db.add(linked)
        db.flush()
    if db.get(PrivacyRequest, linked.customer_id):
        raise HTTPException(403, "Consent has been withdrawn.")
    token, ttl = issue_customer_token(linked.customer_id, settings)
    return {"customer_id": linked.customer_id, "access_token": token, "expires_in": ttl}
