"""Small parsers for what a customer types.

Deliberately conservative: an amount needs a unit or an explicit loan-intent word, and a
bare six-digit number is never treated as a loan (it is usually a pincode).
"""
from __future__ import annotations

import re

CURRENCY = re.compile(r"(?:₹|rs\.?|inr|rupees?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
LAKH = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:lakhs?|lacs?|l\b)", re.I)
THOUSAND = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:k\b|thousand\b)", re.I)
CRORE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:crores?|cr\b)", re.I)
BARE = re.compile(r"\b([0-9]{4,8})\b")
INTENT = re.compile(r"\b(?:loan|borrow|need|want|require|amount|apply|eligible|eligibility|limit)\b", re.I)
NOT_AMOUNT = re.compile(r"\b(?:pincode|pin code|aadhaar|aadhar|otp|account|ifsc|mobile|phone)\b", re.I)
TENURE_MONTHS = re.compile(r"([0-9]{1,2})\s*(?:months?|mo\b)", re.I)
TENURE_YEARS = re.compile(r"([0-9]{1,2})\s*(?:years?|yrs?)\b", re.I)


def _scale(raw: str, multiplier: int) -> int | None:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    return int(round(value * multiplier))


def parse_amount_rupees(text: str) -> int | None:
    if not text or NOT_AMOUNT.search(text):
        return None
    for pattern, multiplier in ((CRORE, 10_000_000), (LAKH, 100_000), (THOUSAND, 1_000), (CURRENCY, 1)):
        match = pattern.search(text)
        if match and (value := _scale(match.group(1), multiplier)) is not None:
            return value
    if INTENT.search(text):
        match = BARE.search(text)
        if match and (value := _scale(match.group(1), 1)) is not None:
            return value
    return None


def parse_tenure_months(text: str, default: int | None = None) -> int | None:
    if match := TENURE_MONTHS.search(text or ""):
        return int(match.group(1))
    if match := TENURE_YEARS.search(text or ""):
        return int(match.group(1)) * 12
    return default
