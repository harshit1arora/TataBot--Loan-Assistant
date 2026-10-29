"""Application lifecycle and underwriting orchestration.

Everything the decision depends on is read server-side: the customer record, the
policy, and the verified income from a stored document. The caller supplies an amount
and a tenure and nothing else.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import NotFoundError, PolicyRejection
from ..models import Application, Customer, DecisionRecord
from ..money import paise_to_rupees, rupees_to_paise
from ..policy import Applicant, CreditPolicy, Outcome, build_policy, decide
from ..services import audit, documents


def create_application(
    db: Session,
    *,
    settings: Settings,
    customer_id: str,
    requested_amount_rupees: int,
    tenure_months: int,
) -> Application:
    policy = build_policy(settings)
    amount_paise = rupees_to_paise(requested_amount_rupees)

    if not policy.min_loan_amount_paise <= amount_paise <= policy.max_loan_amount_paise:
        raise PolicyRejection(
            "Requested amount is outside the permitted range.",
            details={
                "min_rupees": int(paise_to_rupees(policy.min_loan_amount_paise)),
                "max_rupees": int(paise_to_rupees(policy.max_loan_amount_paise)),
            },
        )
    if not policy.min_tenure_months <= tenure_months <= policy.max_tenure_months:
        raise PolicyRejection(
            "Tenure is outside the permitted range.",
            details={
                "min_months": policy.min_tenure_months,
                "max_months": policy.max_tenure_months,
            },
        )

    application = Application(
        customer_id=customer_id,
        requested_amount_paise=amount_paise,
        tenure_months=tenure_months,
        status="submitted",
    )
    db.add(application)
    db.flush()
    audit.record(
        db,
        actor_type="customer",
        actor_id=customer_id,
        action="application.created",
        entity_type="application",
        entity_id=application.id,
        metadata={"amount_paise": amount_paise, "tenure_months": tenure_months},
    )
    return application


def get_owned_application(db: Session, application_id: str, customer_id: str) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.customer_id != customer_id:
        raise NotFoundError("Application not found.")
    return application


def latest_decision(db: Session, application_id: str) -> DecisionRecord | None:
    return db.execute(
        select(DecisionRecord)
        .where(DecisionRecord.application_id == application_id)
        .order_by(DecisionRecord.created_at.desc())
    ).scalars().first()


def evaluate(db: Session, *, settings: Settings, application: Application) -> DecisionRecord:
    """Run the credit policy against an application and persist the decision."""
    policy: CreditPolicy = build_policy(settings)
    customer = db.get(Customer, application.customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")

    verified_income = documents.verified_monthly_income_paise(db, customer.id)
    applicant = Applicant(
        customer_id=customer.id,
        age=customer.age,
        credit_score=customer.credit_score,
        pre_approved_limit_paise=customer.pre_approved_limit_paise,
        verified_income_paise=verified_income,
    )
    decision = decide(policy, applicant, application.requested_amount_paise, application.tenure_months)

    record = DecisionRecord(
        application_id=application.id,
        outcome=decision.outcome.value,
        reason_codes=[reason.value for reason in decision.reasons],
        emi_paise=decision.emi_paise,
        policy_version=decision.policy_version,
        interest_rate_percent=decision.interest_rate_percent,
        tenure_months=decision.tenure_months,
        inputs_snapshot={
            "requested_amount_paise": application.requested_amount_paise,
            "tenure_months": application.tenure_months,
            "credit_score_band": "redacted",  # the raw score is not copied around
            "pre_approved_limit_paise": customer.pre_approved_limit_paise,
            "verified_income_paise": verified_income,
            "policy_version": decision.policy_version,
        },
    )
    db.add(record)

    application.status = {
        Outcome.APPROVE: "approved",
        Outcome.REJECT: "rejected",
        Outcome.REQUIRE_DOCUMENT: "document_required",
    }[decision.outcome]
    db.flush()

    audit.record(
        db,
        actor_type="service",
        actor_id="underwriting",
        action="application.evaluated",
        entity_type="application",
        entity_id=application.id,
        metadata={
            "outcome": decision.outcome.value,
            "reason_codes": [r.value for r in decision.reasons],
            "policy_version": decision.policy_version,
        },
    )
    return record
