"""OfferMart contract, and proof that its EMI maths matches the lending core."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("MOCK_OFFERMART_TOKEN", "test-offermart-token")

from mock_offermart.main import app  # noqa: E402
from mock_offermart.pricing import (  # noqa: E402
    PRODUCTS,
    build_offer,
    compute_emi_paise,
    eligible_products,
    quote,
)

TOKEN = {"x-service-token": "test-offermart-token"}

# --- the core's formula, imported so the two can be compared -----------------
CORE = Path(__file__).resolve().parents[2] / "core"
sys.path.insert(0, str(CORE))
from core_service.money import compute_emi_paise as core_emi  # noqa: E402

CUSTOMER = {
    "id": "CUST001",
    "name": "Asha Verma",
    "monthly_income_paise": 6_000_000,
    "credit_score": 745,
}


def test_emi_matches_the_lending_core_exactly():
    """A quote from OfferMart must equal what the core will sanction."""
    for principal in (1_000_000, 25_000_000, 50_000_000, 72_000_000):
        for rate in (10.99, 12.0, 13.5):
            for tenure in (6, 12, 24, 36, 48, 60):
                assert compute_emi_paise(principal, rate, tenure) == core_emi(
                    principal, rate, tenure
                ), (principal, rate, tenure)


def test_offer_rule_is_six_times_income_capped_by_product():
    offer = build_offer(CUSTOMER)
    assert offer["approved_limit_paise"] == 36_000_000  # 6 × ₹60,000
    assert offer["product"]["code"] == "PL_STANDARD"  # 745 clears 700, not 760
    assert offer["rule"].startswith("approved_limit = min(6 x")


def test_best_product_is_chosen_by_score():
    assert build_offer({**CUSTOMER, "credit_score": 790})["product"]["code"] == "PL_PRIME"
    assert build_offer({**CUSTOMER, "credit_score": 660})["product"]["code"] == "PL_FLEX"


def test_no_product_below_the_floor():
    assert build_offer({**CUSTOMER, "credit_score": 600}) is None
    assert eligible_products(600) == []


def test_quote_breakdown_adds_up():
    result = quote(50_000_000, 36, "PL_STANDARD")
    assert result["total_payable_paise"] == result["emi_paise"] * 36
    assert result["total_interest_paise"] == result["total_payable_paise"] - 50_000_000


@pytest.fixture()
def client():
    return TestClient(app)


def test_health_lists_products(client):
    body = client.get("/health").json()
    assert body["products"] == len(PRODUCTS)


def test_routes_require_the_service_token(client):
    assert client.get("/v1/products").status_code == 401
    assert client.post("/v1/price", json={"principal_paise": 1000000, "tenure_months": 12}).status_code == 401


def test_products_are_listed(client):
    body = client.get("/v1/products", headers=TOKEN).json()
    assert {row["code"] for row in body} == {"PL_PRIME", "PL_STANDARD", "PL_FLEX"}


def test_price_endpoint(client):
    body = client.post(
        "/v1/price",
        json={"principal_paise": 50_000_000, "tenure_months": 36, "product_code": "PL_STANDARD"},
        headers=TOKEN,
    ).json()
    assert body["emi_paise"] == compute_emi_paise(50_000_000, 12.0, 36)


def test_offer_endpoint_pulls_the_profile_from_the_crm(client, monkeypatch):
    """OfferMart must not keep its own copy of the customer."""

    async def fake_fetch(customer_id):
        assert customer_id == "CUST001"
        return CUSTOMER

    monkeypatch.setattr("mock_offermart.main._fetch_customer", fake_fetch)
    body = client.get("/v1/offers/CUST001", headers=TOKEN).json()
    assert body["approved_limit_paise"] == 36_000_000


def test_offer_endpoint_reports_a_crm_outage(client, monkeypatch):
    async def boom(customer_id):
        raise httpx.ConnectError("crm down")

    monkeypatch.setattr("mock_offermart.main._fetch_customer", boom)
    with pytest.raises(httpx.ConnectError):
        client.get("/v1/offers/CUST001", headers=TOKEN)
