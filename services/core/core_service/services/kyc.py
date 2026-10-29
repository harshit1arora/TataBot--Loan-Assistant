"""KYC adapter.

The demo provider checks the phone number against the record on file. A production
deployment replaces ``DemoKycProvider`` with an OTP send/verify flow plus a bureau
and document-verification vendor; the service interface does not change.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from ..models import Customer


@dataclass(frozen=True)
class KycResult:
    phone_verified: bool
    address_verified: bool

    @property
    def all_verified(self) -> bool:
        return self.phone_verified and self.address_verified


class KycProvider(Protocol):
    def verify(self, customer: Customer, phone: str) -> KycResult: ...


class DemoKycProvider:
    """Matches the supplied phone against the registered number. No OTP is sent."""

    name = "demo"

    def verify(self, customer: Customer, phone: str) -> KycResult:
        match = hmac.compare_digest(customer.phone, phone)
        # Address verification is a separate vendor call in production; it stays false
        # here so the UI does not claim something that was never checked.
        return KycResult(phone_verified=match, address_verified=False)


def authenticate(db: Session, customer: Customer, phone: str, provider: KycProvider) -> KycResult:
    result = provider.verify(customer, phone)
    if result.phone_verified and not customer.phone_verified:
        customer.phone_verified = True
        db.flush()
    return result
