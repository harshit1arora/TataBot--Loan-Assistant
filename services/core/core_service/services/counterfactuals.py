"""Illustrative alternatives evaluated with the current deterministic credit policy."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Application, Customer, DecisionRecord, Document
from ..policy import Applicant, Outcome, Reason, build_policy, decide


def alternatives(
    db: Session, settings: Settings, application: Application, decision: DecisionRecord | None
) -> dict | None:
    if not decision or decision.outcome != Outcome.REJECT.value:
        return None
    customer = db.get(Customer, application.customer_id)
    if not customer:
        return None
    snapshot = decision.inputs_snapshot or {}
    evidence = (
        db.get(Document, snapshot.get("evidence_id")) if snapshot.get("evidence_id") else None
    )
    income = None
    if (
        evidence
        and evidence.customer_id == customer.id
        and evidence.status == "extracted"
        and not evidence.requires_review
        and evidence.verified_income_paise == snapshot.get("verified_income_paise")
    ):
        income = evidence.verified_income_paise
    bank = snapshot.get("bank_cross_check") or {}
    bank_review_required = bool(
        bank
        and (bank.get("status") != "matching" or bank.get("signals"))
        and snapshot.get("income_source") != "underwriter_verified"
    )
    applicant = Applicant(
        customer_id=customer.id,
        age=customer.age,
        credit_score=customer.credit_score,
        pre_approved_limit_paise=customer.pre_approved_limit_paise,
        verified_income_paise=income,
        bank_review_required=bank_review_required,
    )
    policy = build_policy(settings)
    original_amount = application.requested_amount_paise
    original_tenure = application.tenure_months

    def outcome(candidate: Applicant, amount: int, months: int):
        if policy.validate_request(amount, months):
            return None
        return decide(policy, candidate, amount, months)

    current = outcome(applicant, original_amount, original_tenure)
    options: list[dict] = []
    result: dict = {
        "policy_version": policy.version,
        "annual_rate_percent": policy.annual_rate_percent,
        "current_outcome": current.outcome.value if current else "outside_range",
        "options": options,
    }
    if current is None or current.outcome != Outcome.REJECT:
        return result

    # Monetary inputs accepted by the API use whole rupees.
    low = (policy.min_loan_amount_paise + 99) // 100
    high = min((original_amount - 100) // 100, policy.max_loan_amount_paise // 100)
    best = None
    while low <= high:
        middle = (low + high) // 2
        candidate = outcome(applicant, middle * 100, original_tenure)
        if candidate and candidate.outcome == Outcome.APPROVE:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best is not None:
        options.append(
            {"type": "maximum_amount", "amount_paise": best * 100, "tenure_months": original_tenure}
        )

    for tenure in range(original_tenure + 1, policy.max_tenure_months + 1):
        candidate = outcome(applicant, original_amount, tenure)
        if candidate and candidate.outcome == Outcome.APPROVE:
            options.append(
                {"type": "minimum_tenure", "amount_paise": original_amount, "tenure_months": tenure}
            )
            break

    if current.reasons == [Reason.FOIR_EXCEEDED] and income is not None and not bank:
        # The reviewer input accepts at most 10 million rupees of monthly income.
        low, high = income // 100 + 1, 10_000_000
        best_income = None
        while low <= high:
            middle = (low + high) // 2
            candidate = outcome(
                replace(applicant, verified_income_paise=middle * 100),
                original_amount,
                original_tenure,
            )
            if candidate and candidate.outcome == Outcome.APPROVE:
                best_income = middle
                high = middle - 1
            else:
                low = middle + 1
        if best_income is not None:
            options.append(
                {
                    "type": "minimum_verified_income",
                    "income_paise": best_income * 100,
                    "amount_paise": original_amount,
                    "tenure_months": original_tenure,
                }
            )
    return result
