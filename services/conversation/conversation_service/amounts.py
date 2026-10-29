"""Loan-amount parsing.

The previous implementation multiplied any figure by 1000 whenever the letter "k"
appeared anywhere in the message, so "50000, ok?" became five crore. This one requires
an explicit unit or an explicit loan-intent word, and it never guesses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CURRENCY_CUES = re.compile(r"(?:₹|rs\.?|inr|rupees?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
LAKH_CUES = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:lakhs?|lacs?|l\b)", re.I)
THOUSAND_CUES = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:k\b|thousand\b)", re.I)
CRORE_CUES = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:crores?|cr\b)", re.I)
BARE_NUMBER = re.compile(r"\b([0-9]{4,8})\b")
INTENT_WORDS = re.compile(
    r"\b(?:loan|borrow|need|want|require|amount|apply|sanction|eligible|eligibility|limit)\b", re.I
)
NOT_AN_AMOUNT = re.compile(r"\b(?:pincode|pin code|aadhaar|aadhar|otp|account|ifsc|mobile|phone)\b", re.I)


@dataclass(frozen=True)
class ParsedAmount:
    rupees: int
    source: str  # which rule matched — useful when explaining the reply


def _to_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _scale(raw: str, multiplier: int) -> int | None:
    """Multiply before rounding, so 2.5 lakh is 2,50,000 and not 2,00,000."""
    value = _to_number(raw)
    if value is None:
        return None
    return int(round(value * multiplier))


def parse_amount(message: str) -> ParsedAmount | None:
    """Return the amount the customer asked for, or None. Never infers from noise."""
    text = message.strip()
    if not text or NOT_AN_AMOUNT.search(text):
        return None

    for pattern, multiplier, source in (
        (CRORE_CUES, 10_000_000, "crore"),
        (LAKH_CUES, 100_000, "lakh"),
        (THOUSAND_CUES, 1_000, "thousand"),
        (CURRENCY_CUES, 1, "currency"),
    ):
        match = pattern.search(text)
        if match and (value := _scale(match.group(1), multiplier)) is not None:
            return ParsedAmount(value, source)

    # A bare figure is only an amount when the sentence is clearly about a loan.
    if (
        INTENT_WORDS.search(text)
        and (match := BARE_NUMBER.search(text))
        and (value := _scale(match.group(1), 1)) is not None
    ):
        return ParsedAmount(value, "bare_with_intent")
    return None


def parse_tenure(message: str) -> int | None:
    if match := re.search(r"([0-9]{1,2})\s*(?:months?|mo\b)", message, re.I):
        return int(match.group(1))
    if match := re.search(r"([0-9]{1,2})\s*(?:years?|yrs?)\b", message, re.I):
        return int(match.group(1)) * 12
    return None


UPLOAD_WORDS = re.compile(r"\b(?:upload|attach|slip|payslip|document|salary slip)\b", re.I)
GREETING_WORDS = re.compile(r"^\s*(?:hi|hello|hey|namaste|good (?:morning|afternoon|evening))\b", re.I)
RESTART_WORDS = re.compile(r"\b(?:new application|apply again|start over|another loan)\b", re.I)

# Deliberately narrow: "help" alone is too common to mean support.
SUPPORT_WORDS = re.compile(
    r"\b(?:contact(?:\s+us)?|support|customer\s*care|helpline|grievance|complain(?:t)?|"
    r"talk\s+to\s+(?:a\s+)?(?:human|agent|someone)|speak\s+to\s+(?:a\s+)?(?:human|agent|someone)|"
    r"call\s+(?:you|someone)|email\s+(?:you|someone))\b",
    re.I,
)


def looks_like_upload(message: str) -> bool:
    return bool(UPLOAD_WORDS.search(message))


def looks_like_greeting(message: str) -> bool:
    return bool(GREETING_WORDS.search(message))


def looks_like_restart(message: str) -> bool:
    return bool(RESTART_WORDS.search(message))


def looks_like_support_request(message: str) -> bool:
    return bool(SUPPORT_WORDS.search(message))


# Question-shaped messages go to the agent graph rather than the application flow.
QUESTION_WORDS = re.compile(
    r"\b(?:what|how|why|which|when|where|who|explain|tell\s+me|is\s+my|are\s+there|"
    r"can\s+i|would\s+i|will\s+i|am\s+i|do\s+i|does\s+it|should\s+i|"
    r"eligible|eligibility|emi|interest\s+rate|documents?|policy|privacy|grievance|prepay)\b",
    re.I,
)


def looks_like_question(message: str) -> bool:
    """A question, not an instruction. Statements like "I need 5 lakh" stay in the flow."""
    text = (message or "").strip()
    if not text:
        return False
    if text.endswith("?"):
        return True
    return bool(QUESTION_WORDS.search(text))
