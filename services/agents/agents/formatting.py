"""Indian money and label formatting, shared by the workers."""
from __future__ import annotations

REASON_LABELS = {
    "within_pre_approved_limit": "within your available limit",
    "emi_within_foir": "the EMI is within 50% of your verified income",
    "credit_score_below_min": "the credit score is below our minimum",
    "amount_above_max_multiple_of_pre_approved": "the amount is more than twice your limit",
    "emi_exceeds_foir_limit": "the EMI would exceed 50% of your verified income",
    "age_out_of_range": "the age is outside our lending range",
    "amount_above_policy_max": "the amount is outside our permitted range",
    "verified_income_document_required": "income needs to be verified from a document",
    "verified_income_unavailable": "income could not be verified",
}


def inr(paise: int | None) -> str:
    """₹ with Indian digit grouping: 50000000 paise -> ₹5,00,000."""
    if paise is None:
        return "—"
    rupees = paise / 100
    whole, _, fraction = f"{abs(rupees):,.2f}".partition(".")
    whole = whole.replace(",", "")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    sign = "-" if rupees < 0 else ""
    return f"₹{sign}{whole}.{fraction}"


def rupees(amount: int) -> str:
    """₹ with Indian digit grouping from a rupee integer."""
    return inr(amount * 100)


def reason_text(code: str) -> str:
    return REASON_LABELS.get(code, code.replace("_", " "))
