"""P0: input validation and the credit policy."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "payload",
    [
        {"requested_amount_rupees": -50000, "tenure_months": 36},
        {"requested_amount_rupees": 0, "tenure_months": 36},
        {"requested_amount_rupees": 100000, "tenure_months": 0},
        {"requested_amount_rupees": 100000, "tenure_months": 600},
        {"requested_amount_rupees": 100000},
        {"tenure_months": 36},
    ],
)
def test_malformed_amounts_and_tenures_are_rejected(client, auth_headers, payload):
    response = client.post("/v1/applications", json=payload, headers=auth_headers)
    assert response.status_code == 422, response.text


def test_client_cannot_supply_interest_rate_or_state(client, auth_headers):
    """The old API let the caller set the rate and the workflow state. Both are gone."""
    response = client.post(
        "/v1/applications",
        json={
            "requested_amount_rupees": 100000,
            "tenure_months": 36,
            "annual_rate": 0,
            "current_state": "sanction",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_amount_above_policy_maximum_is_refused(client, auth_headers):
    response = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 9_000_000, "tenure_months": 36},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "policy_rejection"


def test_approval_within_pre_approved_limit(client, auth_headers):
    response = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 200000, "tenure_months": 36},
        headers=auth_headers,
    )
    body = response.json()
    assert response.status_code == 201
    assert body["decision"]["outcome"] == "approve"
    assert body["decision"]["reason_codes"] == ["within_pre_approved_limit"]
    assert body["decision"]["emi_paise"] > 0
    assert body["decision"]["policy_version"]


def test_above_pre_approved_limit_requires_a_document(client):
    """CUST005: limit 2,50,000, no documents on file. The declared salary does not count."""
    from conftest import token_for

    headers = token_for(client, "CUST005", "9810000005")
    response = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 400000, "tenure_months": 36},
        headers=headers,
    )
    body = response.json()
    assert body["decision"]["outcome"] == "require_document"
    assert body["decision"]["reason_codes"] == ["verified_income_document_required"]
    assert body["status"] == "document_required"


def test_amount_above_twice_the_limit_is_rejected(client, auth_headers):
    response = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 900000, "tenure_months": 36},
        headers=auth_headers,
    )
    body = response.json()
    assert body["decision"]["outcome"] == "reject"
    assert body["decision"]["reason_codes"] == ["amount_above_max_multiple_of_pre_approved"]


def test_low_credit_score_is_rejected(client, other_auth_headers):
    """CUST004 has a score of 690, below the 700 floor."""

    token = client.post(
        "/auth/token", json={"customer_id": "CUST004", "phone": "9810000004"}
    ).json()["access_token"]
    response = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 100000, "tenure_months": 36},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = response.json()
    assert body["decision"]["outcome"] == "reject"
    assert body["decision"]["reason_codes"] == ["credit_score_below_min"]


def test_idempotency_key_prevents_duplicate_applications(client, auth_headers):
    payload = {"requested_amount_rupees": 150000, "tenure_months": 24}
    headers = {**auth_headers, "Idempotency-Key": "retry-abc-123"}
    first = client.post("/v1/applications", json=payload, headers=headers)
    second = client.post("/v1/applications", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["application_id"] == second.json()["application_id"]


def test_policy_module_is_pure_and_versioned():
    from core_service.config import get_settings
    from core_service.policy import Applicant, Outcome, build_policy, decide

    policy = build_policy(get_settings())
    applicant = Applicant(
        customer_id="CUST001",
        age=32,
        credit_score=745,
        pre_approved_limit_paise=30_000_000,
        verified_income_paise=None,
    )
    decision = decide(policy, applicant, requested_amount_paise=20_000_000, tenure_months=36)
    assert decision.outcome is Outcome.APPROVE
    assert decision.policy_version == policy.version
