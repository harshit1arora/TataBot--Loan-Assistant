"""Credit policy — the single source of truth for lending rules.

The LLM layer has no copy of these numbers and cannot influence the outcome. Every
decision records the policy version it was made under, so a decision can be explained
after the policy changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .money import compute_emi_paise


class Outcome(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUIRE_DOCUMENT = "require_document"


class Reason(str, Enum):
    WITHIN_PRE_APPROVED_LIMIT = "within_pre_approved_limit"
    EMI_WITHIN_FOIR = "emi_within_foir"
    CREDIT_SCORE_BELOW_MIN = "credit_score_below_min"
    AGE_OUT_OF_RANGE = "age_out_of_range"
    AMOUNT_ABOVE_POLICY_MAX = "amount_above_policy_max"
    AMOUNT_ABOVE_MAX_MULTIPLE = "amount_above_max_multiple_of_pre_approved"
    DOCUMENT_REQUIRED = "verified_income_document_required"
    FOIR_EXCEEDED = "emi_exceeds_foir_limit"
    INCOME_UNVERIFIED = "verified_income_unavailable"


@dataclass(frozen=True)
class CreditPolicy:
    version: str
    min_credit_score: int
    max_emi_to_income_ratio: float
    pre_approved_multiple: float
    min_loan_amount_paise: int
    max_loan_amount_paise: int
    min_tenure_months: int
    max_tenure_months: int
    default_tenure_months: int
    annual_rate_percent: float
    min_customer_age: int
    max_customer_age: int
    reason_codes: dict[Outcome, list[Reason]] = field(default_factory=dict)

    def validate_request(self, amount_paise: int, tenure_months: int) -> list[Reason]:
        problems: list[Reason] = []
        if amount_paise < self.min_loan_amount_paise or amount_paise > self.max_loan_amount_paise:
            problems.append(Reason.AMOUNT_ABOVE_POLICY_MAX)
        if not self.min_tenure_months <= tenure_months <= self.max_tenure_months:
            problems.append(Reason.AMOUNT_ABOVE_POLICY_MAX)
        return problems


@dataclass(frozen=True)
class Applicant:
    customer_id: str
    age: int
    credit_score: int
    pre_approved_limit_paise: int
    verified_income_paise: int | None  # only from a processed income document


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reasons: list[Reason]
    emi_paise: int | None
    policy_version: str
    interest_rate_percent: float
    tenure_months: int


def decide(
    policy: CreditPolicy,
    applicant: Applicant,
    requested_amount_paise: int,
    tenure_months: int,
) -> Decision:
    """Deterministic underwriting. No LLM, no randomness, no network."""
    reasons: list[Reason] = []

    def reject(reason: Reason) -> Decision:
        return Decision(
            outcome=Outcome.REJECT,
            reasons=reasons + [reason],
            emi_paise=None,
            policy_version=policy.version,
            interest_rate_percent=policy.annual_rate_percent,
            tenure_months=tenure_months,
        )

    if not policy.min_customer_age <= applicant.age <= policy.max_customer_age:
        return reject(Reason.AGE_OUT_OF_RANGE)
    if applicant.credit_score < policy.min_credit_score:
        return reject(Reason.CREDIT_SCORE_BELOW_MIN)
    if requested_amount_paise > int(applicant.pre_approved_limit_paise * policy.pre_approved_multiple):
        return reject(Reason.AMOUNT_ABOVE_MAX_MULTIPLE)

    if requested_amount_paise <= applicant.pre_approved_limit_paise:
        emi = compute_emi_paise(requested_amount_paise, policy.annual_rate_percent, tenure_months)
        return Decision(
            outcome=Outcome.APPROVE,
            reasons=[Reason.WITHIN_PRE_APPROVED_LIMIT],
            emi_paise=emi,
            policy_version=policy.version,
            interest_rate_percent=policy.annual_rate_percent,
            tenure_months=tenure_months,
        )

    # Above the pre-approved limit: requires verified income from a processed document.
    if applicant.verified_income_paise is None:
        return Decision(
            outcome=Outcome.REQUIRE_DOCUMENT,
            reasons=[Reason.DOCUMENT_REQUIRED],
            emi_paise=None,
            policy_version=policy.version,
            interest_rate_percent=policy.annual_rate_percent,
            tenure_months=tenure_months,
        )

    emi = compute_emi_paise(requested_amount_paise, policy.annual_rate_percent, tenure_months)
    max_emi = int(applicant.verified_income_paise * policy.max_emi_to_income_ratio)
    if emi > max_emi:
        return Decision(
            outcome=Outcome.REJECT,
            reasons=[Reason.FOIR_EXCEEDED],
            emi_paise=emi,
            policy_version=policy.version,
            interest_rate_percent=policy.annual_rate_percent,
            tenure_months=tenure_months,
        )
    return Decision(
        outcome=Outcome.APPROVE,
        reasons=[Reason.EMI_WITHIN_FOIR],
        emi_paise=emi,
        policy_version=policy.version,
        interest_rate_percent=policy.annual_rate_percent,
        tenure_months=tenure_months,
    )


def build_policy(settings) -> CreditPolicy:
    from .money import rupees_to_paise

    return CreditPolicy(
        version=settings.policy_version,
        min_credit_score=settings.min_credit_score,
        max_emi_to_income_ratio=settings.max_emi_to_income_ratio,
        pre_approved_multiple=settings.pre_approved_multiple,
        min_loan_amount_paise=rupees_to_paise(settings.min_loan_amount_rupees),
        max_loan_amount_paise=rupees_to_paise(settings.max_loan_amount_rupees),
        min_tenure_months=settings.min_tenure_months,
        max_tenure_months=settings.max_tenure_months,
        default_tenure_months=settings.default_tenure_months,
        annual_rate_percent=settings.annual_rate_percent,
        min_customer_age=settings.min_customer_age,
        max_customer_age=settings.max_customer_age,
    )
