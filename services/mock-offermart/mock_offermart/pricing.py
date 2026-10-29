"""Pricing rules and the EMI formula.

The EMI maths here mirrors the lending core's `money.compute_emi_paise` exactly; a test in
this service asserts the two agree on a table of inputs, so a quote from OfferMart can never
drift from what the core will sanction.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

PRODUCTS: list[dict] = [
    {
        "code": "PL_PRIME",
        "name": "Prime Personal Loan",
        "annual_rate_percent": 10.99,
        "min_score": 760,
        "min_amount_paise": 1_000_000,
        "max_amount_paise": 500_000_000,
        "tenure_options": [12, 24, 36, 48, 60],
    },
    {
        "code": "PL_STANDARD",
        "name": "Standard Personal Loan",
        "annual_rate_percent": 12.0,
        "min_score": 700,
        "min_amount_paise": 1_000_000,
        "max_amount_paise": 500_000_000,
        "tenure_options": [12, 24, 36, 48, 60],
    },
    {
        "code": "PL_FLEX",
        "name": "Flex Personal Loan",
        "annual_rate_percent": 13.5,
        "min_score": 650,
        "min_amount_paise": 500_000,
        "max_amount_paise": 200_000_000,
        "tenure_options": [6, 12, 18, 24, 36],
    },
]

# Six months of income is the same conservative multiple the lending core uses for a
# derived limit, so an offer quoted here is never larger than what the core will consider.
INCOME_MULTIPLE = 6


def compute_emi_paise(principal_paise: int, annual_rate_percent: float, tenure_months: int) -> int:
    if principal_paise <= 0 or tenure_months <= 0 or not 0 < annual_rate_percent < 100:
        raise ValueError("invalid pricing inputs")
    principal = Decimal(principal_paise) / 100
    monthly = Decimal(str(annual_rate_percent)) / Decimal(1200)
    factor = (Decimal(1) + monthly) ** tenure_months
    emi = principal * monthly * factor / (factor - Decimal(1))
    return int((emi * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def eligible_products(credit_score: int, requested_paise: int | None = None) -> list[dict]:
    return [
        product
        for product in PRODUCTS
        if credit_score >= product["min_score"]
        and (requested_paise is None or product["min_amount_paise"] <= requested_paise <= product["max_amount_paise"])
    ]


def build_offer(customer: dict) -> dict | None:
    """The published offer rule: 6 × monthly income, capped by the best product's ceiling."""
    income_paise = int(customer["monthly_income_paise"])
    score = int(customer["credit_score"])
    products = eligible_products(score)
    if not products:
        return None

    best = products[0]  # PRODUCTS is ordered best-first
    limit = min(income_paise * INCOME_MULTIPLE, best["max_amount_paise"])
    return {
        "customer_id": customer["id"],
        "customer_name": customer["name"],
        "credit_score": score,
        "approved_limit_paise": limit,
        "income_multiple": INCOME_MULTIPLE,
        "product": {
            "code": best["code"],
            "name": best["name"],
            "annual_rate_percent": best["annual_rate_percent"],
            "tenure_options": best["tenure_options"],
        },
        "alternatives": [
            {"code": p["code"], "annual_rate_percent": p["annual_rate_percent"]}
            for p in products[1:]
        ],
        "rule": "approved_limit = min(6 x declared monthly income, product ceiling)",
    }


# A band is enough to pick a product, so the raw score never has to leave the core service.
BAND_TO_SCORE = {"excellent": 760, "good": 700, "fair": 650}


def build_offer_for_band(band: str, monthly_income_paise: int, customer_id: str | None = None) -> dict | None:
    """Offer for a profile supplied by the caller.

    Used when the customer is not in the CRM — for example someone who self-registered
    with the lender minutes ago. Same published rule, no CRM dependency.
    """
    score = BAND_TO_SCORE.get(band)
    if score is None:
        return None
    synthetic = {
        "id": customer_id or "UNKNOWN",
        "name": "Customer",
        "monthly_income_paise": monthly_income_paise,
        "credit_score": score,
    }
    return build_offer(synthetic)


DEFAULT_PRODUCT = "PL_STANDARD"


def quote(principal_paise: int, tenure_months: int, product_code: str | None = None) -> dict:
    """Price a loan.

    With no product code, price at the **standard** product. Never the best one: quoting
    a rate the customer may not qualify for would understate the cost of borrowing.
    """
    product = next((p for p in PRODUCTS if p["code"] == product_code), None)
    if product is None:
        product = next(p for p in PRODUCTS if p["code"] == DEFAULT_PRODUCT)
    emi = compute_emi_paise(principal_paise, product["annual_rate_percent"], tenure_months)
    return {
        "product_code": product["code"],
        "product_defaulted": product_code is None or product_code != product["code"],
        "product_name": product["name"],
        "annual_rate_percent": product["annual_rate_percent"],
        "principal_paise": principal_paise,
        "tenure_months": tenure_months,
        "emi_paise": emi,
        "total_payable_paise": emi * tenure_months,
        "total_interest_paise": emi * tenure_months - principal_paise,
    }
