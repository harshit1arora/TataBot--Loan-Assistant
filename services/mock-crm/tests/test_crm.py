"""MockCRM contract."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("MOCK_CRM_TOKEN", "test-crm-token")

from mock_crm.main import app  # noqa: E402

TOKEN = {"x-service-token": "test-crm-token"}


@pytest.fixture()
def client():
    return TestClient(app)


def test_health_is_open(client):
    assert client.get("/health").json()["service"] == "mock-crm"


def test_every_data_route_requires_the_service_token(client):
    for method, path in [
        ("get", "/v1/customers"),
        ("get", "/v1/customers/CUST001"),
        ("get", "/v1/customers/CUST001/kyc"),
        ("get", "/v1/customers/CUST001/interactions"),
    ]:
        assert getattr(client, method)(path).status_code == 401
    assert client.post("/v1/customers/CUST001/interactions", json={"summary": "x y z"}).status_code == 401


def test_a_wrong_token_is_rejected(client):
    assert client.get("/v1/customers", headers={"x-service-token": "nope"}).status_code == 401


def test_profile_carries_what_the_agents_need(client):
    body = client.get("/v1/customers/CUST001", headers=TOKEN).json()
    assert body["name"] == "Asha Verma"
    assert body["monthly_income_paise"] == 6_000_000
    assert body["credit_score"] == 745
    assert body["employment"] == "salaried"
    assert body["kyc"]["phone_verified"] is True


def test_unknown_customer_is_a_404(client):
    assert client.get("/v1/customers/CUST999", headers=TOKEN).status_code == 404


def test_kyc_can_be_updated_and_read_back(client):
    updated = client.post(
        "/v1/customers/CUST002/kyc/verify",
        json={"field": "pan_verified", "value": True},
        headers=TOKEN,
    ).json()
    assert updated["pan_verified"] is True
    assert client.get("/v1/customers/CUST002/kyc", headers=TOKEN).json()["pan_verified"] is True


def test_interactions_are_appended_and_listed(client):
    created = client.post(
        "/v1/customers/CUST003/interactions",
        json={"channel": "chat", "summary": "Asked about EMI for 5 lakh over 36 months"},
        headers=TOKEN,
    )
    assert created.status_code == 200
    listed = client.get("/v1/customers/CUST003/interactions", headers=TOKEN).json()
    assert any(row["id"] == created.json()["id"] for row in listed)


def test_interaction_requires_a_real_summary(client):
    assert (
        client.post(
            "/v1/customers/CUST001/interactions", json={"summary": "hi"}, headers=TOKEN
        ).status_code
        == 422
    )
