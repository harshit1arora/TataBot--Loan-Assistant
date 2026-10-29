"""Money and EMI arithmetic.

Amounts are stored and returned as integer paise, so no float ever touches a rupee
value. Decimals are used for the calculation itself and rounded once, at the end.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("1")


def rupees_to_paise(rupees: int | Decimal | str) -> int:
    value = Decimal(str(rupees)) * 100
    return int(value.quantize(PAISE, rounding=ROUND_HALF_UP))


def paise_to_rupees(paise: int) -> Decimal:
    return (Decimal(paise) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_inr(paise: int) -> str:
    """Indian digit grouping: 12,34,567.89"""
    value = paise_to_rupees(paise)
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return f"{sign}{whole}.{frac}"


def compute_emi_paise(principal_paise: int, annual_rate_percent: float, tenure_months: int) -> int:
    """Standard reducing-balance EMI, rounded to the paisa.

    Raises ValueError on inputs the caller was supposed to have validated.
    """
    if principal_paise <= 0:
        raise ValueError("principal must be positive")
    if tenure_months <= 0:
        raise ValueError("tenure_months must be positive")
    if not 0 < annual_rate_percent < 100:
        raise ValueError("annual_rate_percent out of range")

    principal = Decimal(principal_paise) / 100
    monthly_rate = Decimal(str(annual_rate_percent)) / Decimal(1200)
    factor = (Decimal(1) + monthly_rate) ** tenure_months
    emi = principal * monthly_rate * factor / (factor - Decimal(1))
    return int((emi * 100).quantize(PAISE, rounding=ROUND_HALF_UP))


def total_repayment_paise(emi_paise: int, tenure_months: int) -> int:
    return emi_paise * tenure_months
