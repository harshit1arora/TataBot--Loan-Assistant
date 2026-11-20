"""Counterfactuals must be policy-checked, private and accurate at boundaries."""

from dataclasses import replace
from uuid import uuid4

from conftest import make_salary_pdf, token_for
from core_service.config import get_settings
from core_service.db import SessionLocal
from core_service.models import Document
from core_service.policy import Applicant, Outcome, build_policy, decide


def customer(client, score=745):
    phone = "9" + str(int(uuid4().hex[:8], 16) % 10**9).zfill(9)
    response = client.post(
        "/v1/customers",
        json={
            "name": "Scenario Test",
            "age": 34,
            "phone": phone,
            "email": "scenario@example.test",
            "city": "Pune",
            "declared_monthly_income_rupees": 60000,
            "declared_credit_score": score,
        },
    )
    assert response.status_code == 201, response.text
    return token_for(client, response.json()["customer_id"], phone)


def test_decline_suggestions_match_policy_boundaries(client, other_auth_headers):
    headers = customer(client)
    application = client.post(
        "/v1/applications",
        headers=headers,
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
    ).json()
    app_id = application["application_id"]
    doc = client.post(
        "/v1/documents",
        headers=headers,
        data={"application_id": app_id, "doc_type": "salary_slip"},
        files={"file": ("pay.pdf", make_salary_pdf(30000), "application/pdf")},
    ).json()
    assessed = client.post(
        f"/v1/applications/{app_id}/documents/{doc['document_id']}/assess", headers=headers
    )
    assert assessed.status_code == 200 and assessed.json()["application"]["status"] == "rejected"
    path = f"/v1/applications/{app_id}/summary"
    assert client.get(path, headers=other_auth_headers).status_code == 404
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()["counterfactuals"]
    options = {item["type"]: item for item in result["options"]}
    assert set(options) == {"maximum_amount", "minimum_tenure", "minimum_verified_income"}
    policy = build_policy(get_settings())
    applicant = Applicant(
        customer_id="test",
        age=34,
        credit_score=745,
        pre_approved_limit_paise=36000000,
        verified_income_paise=3000000,
    )
    amount = options["maximum_amount"]["amount_paise"]
    assert decide(policy, applicant, amount, 36).outcome == Outcome.APPROVE
    assert decide(policy, applicant, amount + 100, 36).outcome == Outcome.REJECT
    months = options["minimum_tenure"]["tenure_months"]
    assert decide(policy, applicant, 50000000, months).outcome == Outcome.APPROVE
    assert decide(policy, applicant, 50000000, months - 1).outcome == Outcome.REJECT
    income = options["minimum_verified_income"]["income_paise"]
    assert (
        decide(policy, replace(applicant, verified_income_paise=income), 50000000, 36).outcome
        == Outcome.APPROVE
    )
    assert (
        decide(policy, replace(applicant, verified_income_paise=income - 100), 50000000, 36).outcome
        == Outcome.REJECT
    )
    with SessionLocal.begin() as db:
        db.get(Document, doc["document_id"]).requires_review = True
    stale = client.get(path, headers=headers).json()["counterfactuals"]
    assert stale["current_outcome"] == "require_document" and stale["options"] == []


def test_credit_score_cannot_be_fixed_by_amount_or_tenure(client):
    headers = customer(client, 650)
    created = client.post(
        "/v1/applications",
        headers=headers,
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
    ).json()
    result = client.get(
        "/v1/applications/" + created["application_id"] + "/summary", headers=headers
    ).json()
    assert result["application"]["status"] == "rejected"
    assert result["counterfactuals"]["options"] == []


def test_bank_statement_does_not_get_reused_for_higher_income(client):
    from test_bank_statement import credits

    headers = customer(client)
    application = client.post(
        "/v1/applications",
        headers=headers,
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
    ).json()
    app_id = application["application_id"]
    path = f"/v1/applications/{app_id}/bank-statement"
    assert client.post(path, headers=headers, json=credits(3000000)).status_code == 200
    doc = client.post(
        "/v1/documents",
        headers=headers,
        data={"application_id": app_id, "doc_type": "salary_slip"},
        files={"file": ("pay.pdf", make_salary_pdf(30000), "application/pdf")},
    ).json()
    assessed = client.post(
        f"/v1/applications/{app_id}/documents/{doc['document_id']}/assess", headers=headers
    )
    assert assessed.json()["application"]["status"] == "rejected"
    summary = client.get(f"/v1/applications/{app_id}/summary", headers=headers).json()
    assert summary["bank_cross_check"]["status"] == "matching"
    assert "minimum_verified_income" not in {
        option["type"] for option in summary["counterfactuals"]["options"]
    }
