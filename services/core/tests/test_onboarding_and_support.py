"""Self-service onboarding, real-time decisions on a new customer's own data, and support tickets."""
from __future__ import annotations

import pytest
from conftest import token_for

NEW_CUSTOMER = {
    "name": "Ritu Malhotra",
    "phone": "9812345670",
    "email": "ritu.malhotra@example.com",
    "age": 31,
    "city": "Jaipur",
    "declared_monthly_income_rupees": 120000,
    "declared_credit_score": 768,
}


def register(client, **overrides):
    payload = {**NEW_CUSTOMER, **overrides}
    return client.post("/v1/customers", json=payload)


def test_a_new_person_can_register_and_is_not_one_of_the_seeded_customers(client):
    response = register(client)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["customer_id"].startswith("CUST")
    assert body["customer_id"] not in {f"CUST00{i}" for i in range(1, 10)}
    assert body["profile"]["name"] == "Ritu Malhotra"
    # Provenance is explicit, so a decision can say what it trusted.
    assert body["profile"]["score_source"] == "self_declared"
    assert body["profile"]["limit_source"] == "indicative"
    # 6 × 1,20,000 = 7,20,000, rounded to the nearest thousand.
    assert body["profile"]["pre_approved_limit_paise"] == 720_000 * 100


def test_the_indicative_limit_is_capped_by_policy(client):
    body = register(
        client, phone="9812345671", email="big@example.com", declared_monthly_income_rupees=900000
    ).json()
    # 6 × 9,00,000 = 54,00,000, capped at the policy ceiling of 50,00,000.
    assert body["profile"]["pre_approved_limit_paise"] == 5_000_000 * 100


@pytest.mark.parametrize(
    "overrides",
    [
        {"age": 17, "phone": "9812345672", "email": "a1@example.com"},
        {"age": 61, "phone": "9812345673", "email": "a2@example.com"},
        {"declared_credit_score": 250, "phone": "9812345674", "email": "a3@example.com"},
        {"declared_monthly_income_rupees": 1000, "phone": "9812345675", "email": "a4@example.com"},
        {"phone": "12345"},
        {"email": "not-an-email"},
        {"name": "X"},
    ],
)
def test_registration_rejects_details_the_policy_cannot_lend_to(client, overrides):
    assert register(client, **overrides).status_code == 422


def test_a_mobile_number_cannot_be_registered_twice(client):
    first = register(client, phone="9812345676", email="dup@example.com")
    assert first.status_code == 201
    second = register(client, phone="9812345676", email="dup2@example.com")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


def test_a_registered_customer_gets_a_real_decision_on_their_own_numbers(client):
    """The whole point: no pre-fed record, the decision uses what they just entered."""
    customer_id = register(client, phone="9812345677", email="live@example.com").json()["customer_id"]
    auth = token_for(client, customer_id, "9812345677")

    profile = client.get("/v1/customers/me", headers=auth).json()
    assert profile["customer_id"] == customer_id
    assert profile["credit_score_band"] == "excellent"

    # Within the derived limit (7,20,000) -> approved without any document.
    application = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 600000, "tenure_months": 36},
        headers=auth,
    ).json()
    assert application["decision"]["outcome"] == "approve"
    assert application["decision"]["reason_codes"] == ["within_pre_approved_limit"]
    assert application["decision"]["emi_paise"] > 0

    # Above it -> the document path, exactly as for a seeded customer.
    above = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 900000, "tenure_months": 36},
        headers=auth,
    ).json()
    assert above["decision"]["outcome"] == "require_document"

    # And the application is persisted, so it is readable afterwards.
    listed = client.get("/v1/applications", headers=auth).json()
    assert len(listed) == 2


def test_a_self_declared_score_below_the_floor_is_declined(client):
    customer_id = register(
        client,
        phone="9812345678",
        email="low@example.com",
        declared_credit_score=640,
    ).json()["customer_id"]
    auth = token_for(client, customer_id, "9812345678")

    application = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 100000, "tenure_months": 24},
        headers=auth,
    ).json()
    assert application["decision"]["outcome"] == "reject"
    assert application["decision"]["reason_codes"] == ["credit_score_below_min"]


# --- contact us -------------------------------------------------------------
def test_contact_message_can_be_sent_without_signing_in(client):
    response = client.post(
        "/v1/support/messages",
        json={
            "name": "Anonymous Visitor",
            "contact": "visitor@example.com",
            "topic": "general",
            "message": "I could not complete the salary slip upload on mobile.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["reference"].startswith("SUP-")
    assert body["status"] == "open"
    assert body["expected_response"]


def test_contact_message_is_stored_and_readable_by_its_owner_only(client):
    customer_id = register(client, phone="9812345679", email="ticket@example.com").json()["customer_id"]
    auth = token_for(client, customer_id, "9812345679")
    other = token_for(client, "CUST001", "9810000001")

    created = client.post(
        "/v1/support/messages",
        json={
            "name": "Ritu Malhotra",
            "contact": "9812345679",
            "topic": "grievance",
            "message": "Please review the decline reason on my application.",
        },
        headers=auth,
    ).json()

    mine = client.get("/v1/support/messages", headers=auth).json()
    assert [row["reference"] for row in mine] == [created["reference"]]
    assert mine[0]["topic"] == "grievance"

    assert client.get("/v1/support/messages", headers=other).json() == []
    assert client.get("/v1/support/messages").status_code == 401


def test_contact_message_validates_topic_and_length(client):
    short = client.post(
        "/v1/support/messages",
        json={"name": "A B", "contact": "a@b.com", "topic": "general", "message": "hi"},
    )
    assert short.status_code == 422
    bad_topic = client.post(
        "/v1/support/messages",
        json={
            "name": "A B",
            "contact": "a@b.com",
            "topic": "compliment",
            "message": "This topic is not in the allowed set.",
        },
    )
    assert bad_topic.status_code == 422


# --- service-scoped eligibility preview (used by the agent layer) ------------
def test_agent_can_preview_eligibility_without_creating_an_application(client, service_headers):
    before = len(client.get("/v1/applications", headers=token_for(client, "CUST003", "9810000003")).json())

    response = client.post(
        "/internal/eligibility/preview",
        json={"customer_id": "CUST003", "amount_rupees": 300000, "tenure_months": 36},
        headers=service_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "approve"
    assert body["reason_codes"] == ["within_pre_approved_limit"]
    assert body["emi_paise"] > 0
    assert body["policy_version"]

    after = len(client.get("/v1/applications", headers=token_for(client, "CUST003", "9810000003")).json())
    assert after == before, "a preview must not persist an application"


def test_preview_matches_what_the_real_application_decides(client, service_headers):
    """The agent's explanation and the real decision must never disagree."""
    auth = token_for(client, "CUST009", "9810000009")
    preview = client.post(
        "/internal/eligibility/preview",
        json={"customer_id": "CUST009", "amount_rupees": 200000, "tenure_months": 24},
        headers=service_headers,
    ).json()
    real = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 200000, "tenure_months": 24},
        headers=auth,
    ).json()["decision"]

    assert preview["outcome"] == real["outcome"]
    assert preview["reason_codes"] == real["reason_codes"]
    assert preview["emi_paise"] == real["emi_paise"]


def test_preview_requires_a_service_token(client, auth_headers):
    response = client.post(
        "/internal/eligibility/preview",
        json={"customer_id": "CUST001", "amount_rupees": 100000, "tenure_months": 12},
        headers=auth_headers,
    )
    assert response.status_code == 403


def test_preview_rejects_amounts_outside_policy(client, service_headers):
    response = client.post(
        "/internal/eligibility/preview",
        json={"customer_id": "CUST001", "amount_rupees": 99_000_000, "tenure_months": 12},
        headers=service_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "policy_rejection"


def test_service_can_read_a_document_for_verification(client, service_headers, auth_headers):
    from conftest import make_salary_pdf, process_extraction_jobs

    document_id = client.post(
        "/v1/documents",
        files={"file": ("slip.pdf", make_salary_pdf(85000), "application/pdf")},
        data={"doc_type": "salary_slip"},
        headers=auth_headers,
    ).json()["document_id"]
    process_extraction_jobs()

    body = client.get(f"/internal/documents/{document_id}", headers=service_headers).json()
    assert body["status"] == "extracted"
    assert body["verified_income_paise"] == 8_500_000
    assert client.get(f"/internal/documents/{document_id}").status_code == 401
