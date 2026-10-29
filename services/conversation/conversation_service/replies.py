"""Deterministic reply templates.

Every number a customer reads comes from here or from a core-service response. The LLM
may add a sentence of warmth, never a figure.
"""
from __future__ import annotations

from .money import format_inr


def greeting(first_name: str, limit_paise: int | None, limit_source: str = "offered") -> str:
    lines = [f"Hi {first_name}, I can help you apply for a personal loan today."]
    if limit_paise:
        # A derived limit is not an offer, so it must not be described as one.
        label = "indicative limit" if limit_source == "indicative" else "pre-approved limit"
        lines.append(f"Your {label} is {format_inr(limit_paise)}.")
    lines.append("How much would you like to borrow, and for how many months?")
    return " ".join(lines)


def amount_missing() -> str:
    return (
        "I need the loan amount to check your eligibility. For example: "
        "\"I need 2 lakh for 36 months\"."
    )


def approved(amount_paise: int, emi_paise: int, tenure_months: int, rate: float) -> str:
    return (
        f"Good news — your loan of {format_inr(amount_paise)} is approved. "
        f"The EMI is {format_inr(emi_paise)} for {tenure_months} months at {rate:.2f}% p.a. "
        "Your sanction letter is ready to download below."
    )


def rejected(reasons: list[str]) -> str:
    readable = {
        "credit_score_below_min": "your credit score is below our current minimum",
        "amount_above_max_multiple_of_pre_approved": "the amount is more than twice your pre-approved limit",
        "emi_exceeds_foir_limit": "the EMI would exceed 50% of your verified monthly income",
        "age_out_of_range": "your age is outside our lending range",
        "amount_above_policy_max": "the amount is outside our permitted range",
        "verified_income_document_required": "we need proof of income for this amount",
        "verified_income_unavailable": "we could not verify your income",
    }
    why = "; ".join(readable.get(reason, reason.replace("_", " ")) for reason in reasons) or "our policy criteria"
    return (
        f"I'm sorry — we can't approve this application because {why}. "
        "You can apply for a lower amount, or try again after six months. "
        "If you believe this is wrong, please contact our grievance team."
    )


def document_required(amount_paise: int) -> str:
    return (
        f"{format_inr(amount_paise)} is above your pre-approved limit, so I need your latest "
        "salary slip before I can decide. Upload a PDF or a clear photo and I'll continue "
        "automatically. Your declared salary alone isn't enough for this check."
    )


def document_received(status: str, requires_review: bool, income_paise: int | None) -> str:
    if requires_review or income_paise is None:
        return (
            "Thanks — I've received the document, but I couldn't read the salary figure "
            "confidently enough to use it. It's with our review team and we'll come back to you."
        )
    return f"Thanks — I've read your salary slip and verified a monthly income of {format_inr(income_paise)}."


def document_pending() -> str:
    return "I still need your salary slip to continue. Use the upload button, or attach a PDF."


def sanction_ready(document_id: str, amount_paise: int) -> str:
    return (
        f"Your sanction letter for {format_inr(amount_paise)} is attached below. "
        "It is a simulated document for this demonstration and creates no lending obligation."
    )


def restart() -> str:
    return "Happy to start a new application. How much would you like to borrow, and for how many months?"


def contact_options() -> str:
    """Shown when the customer asks for a human. Every channel is a placeholder."""
    return (
        "You can reach a person on 1800-000-0000 (Mon–Sat, 9am–7pm IST), or send a message here "
        "and I'll log it with a reference you can quote. For a formal complaint, the grievance "
        "team responds within one working day."
    )


def contact_logged(reference: str) -> str:
    return (
        f"Thanks — your message is logged as {reference}. Someone from the team will respond "
        "within one working day. You can quote that reference in any follow-up."
    )


def smalltalk(state: str) -> str:
    return (
        "I can help with a personal loan application, your EMI estimate, or the status of "
        "an application you've already started. What would you like to do?"
    )


def unavailable() -> str:
    return (
        "I can't reach the lending service right now, so I can't quote figures or make a "
        "decision. Please try again in a moment."
    )


def agents_unavailable() -> str:
    return (
        "I can't reach the advisory agents right now, so I won't guess at an answer. "
        "I can still take your application — or try that question again in a moment."
    )


def rate_limited() -> str:
    return "You're sending messages faster than I can process them. Please wait a moment."
