"""Self-service onboarding.

A new customer registers with their own details instead of picking from the seeded demo
set. Two honesty rules apply:

* **Credit score** is self-declared. There is no bureau integration here, so the record
  says `score_source = "self_declared"` and every decision snapshot carries that. In a
  real deployment this field comes from a bureau pull and the applicant never types it.
* **Pre-approved limit** is *derived*, not offered: `INCOME_MULTIPLE × declared monthly
  income`, capped by policy. The record says `limit_source = "indicative"`, and the UI
  shows it as indicative. It is also capped below the policy ceiling so that a
  self-registered customer can still exercise the document path.
"""
from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ConflictError, ValidationAppError
from ..models import Customer
from ..money import paise_to_rupees, rupees_to_paise
from ..policy import build_policy
from ..services import audit

# Six months of declared income is a deliberately conservative indicative multiple.
INCOME_MULTIPLE = 6
# Round the derived limit down to a clean thousand rupees.
ROUND_TO_RUPEES = 1_000


def derive_indicative_limit_paise(declared_income_paise: int, settings: Settings) -> int:
    policy = build_policy(settings)
    raw = declared_income_paise * INCOME_MULTIPLE
    rounded = int(paise_to_rupees(raw)) // ROUND_TO_RUPEES * ROUND_TO_RUPEES
    return min(rupees_to_paise(rounded), policy.max_loan_amount_paise)


def _next_customer_id(db: Session) -> str:
    """CUST### after the seeded set, so ids stay readable in logs and support."""
    highest = db.execute(
        select(func.max(Customer.id)).where(Customer.id.like("CUST%"))
    ).scalar()
    try:
        number = int(str(highest)[4:]) + 1 if highest else 1
    except ValueError:
        number = 1
    candidate = f"CUST{number:03d}"
    while db.get(Customer, candidate) is not None:  # extremely unlikely, but be safe
        number += 1
        candidate = f"CUST{number:03d}"
    return candidate


def register(
    db: Session,
    *,
    settings: Settings,
    name: str,
    phone: str,
    email: str,
    age: int,
    city: str,
    declared_monthly_income_rupees: int,
    declared_credit_score: int,
) -> Customer:
    policy = build_policy(settings)

    if not policy.min_customer_age <= age <= policy.max_customer_age:
        raise ValidationAppError(
            f"Age must be between {policy.min_customer_age} and {policy.max_customer_age}.",
            details={"min": policy.min_customer_age, "max": policy.max_customer_age},
        )
    if not 300 <= declared_credit_score <= 900:
        raise ValidationAppError("Credit score must be between 300 and 900.")
    if declared_monthly_income_rupees < 5_000:
        raise ValidationAppError("Declared monthly income must be at least ₹5,000.")

    if db.execute(select(Customer).where(Customer.phone == phone)).scalars().first():
        raise ConflictError(
            "That mobile number is already registered. Sign in instead.",
            details={"field": "phone"},
        )

    income_paise = rupees_to_paise(declared_monthly_income_rupees)
    customer = Customer(
        id=_next_customer_id(db),
        name=name.strip()[:120],
        age=age,
        city=city.strip()[:80],
        phone=phone,
        email=email.strip().lower()[:160],
        pre_approved_limit_paise=derive_indicative_limit_paise(income_paise, settings),
        declared_salary_paise=income_paise,
        credit_score=declared_credit_score,
        source="self_registered",
        score_source="self_declared",
        limit_source="indicative",
    )
    db.add(customer)
    db.flush()

    audit.record(
        db,
        actor_type="customer",
        actor_id=customer.id,
        action="customer.registered",
        entity_type="customer",
        entity_id=customer.id,
        metadata={
            "source": "self_registered",
            "score_source": "self_declared",
            "limit_source": "indicative",
            "declared_income_paise": income_paise,
        },
    )
    return customer


def issue_otp() -> str:
    """Placeholder for the OTP that a production deployment would send by SMS.

    Not used for authentication here — it exists so the shape of the real flow is
    visible, and so nothing pretends a code was verified when none was.
    """
    return f"{secrets.randbelow(900000) + 100000}"
