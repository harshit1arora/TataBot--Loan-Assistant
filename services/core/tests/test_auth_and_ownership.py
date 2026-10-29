"""P0: authentication, authorisation and ownership."""
from __future__ import annotations

from conftest import CUSTOMER


def test_health_is_liveness_only(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["checks"] == {}


def test_ready_checks_dependencies(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_protected_route_rejects_missing_token(client):
    response = client.get("/v1/customers/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_protected_route_rejects_garbage_token(client):
    response = client.get("/v1/customers/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_login_requires_matching_phone(client):
    response = client.post("/auth/token", json={"customer_id": "CUST001", "phone": "9810000999"})
    assert response.status_code == 401
    assert "match" in response.json()["error"]["message"].lower()


def test_login_rejects_malformed_input(client):
    assert client.post("/auth/token", json={"customer_id": "CUST001", "phone": "12345"}).status_code == 422


def test_profile_comes_from_the_token(client, auth_headers):
    body = client.get("/v1/customers/me", headers=auth_headers).json()
    assert body["customer_id"] == CUSTOMER["customer_id"]
    # The raw score is never exposed; only a band.
    assert "credit_score" not in body
    assert body["credit_score_band"] in {"excellent", "good", "fair"}


def test_service_token_cannot_act_as_a_customer(client, service_headers):
    assert client.get("/v1/customers/me", headers=service_headers).status_code == 403


def test_customer_token_cannot_use_internal_service_route(client, auth_headers):
    response = client.get("/internal/customers/CUST002/summary", headers=auth_headers)
    assert response.status_code == 403


def test_customer_cannot_read_another_customers_application(client, auth_headers, other_auth_headers):
    created = client.post(
        "/v1/applications", json={"requested_amount_rupees": 200000, "tenure_months": 36}, headers=auth_headers
    )
    assert created.status_code == 201
    application_id = created.json()["application_id"]

    response = client.get(f"/v1/applications/{application_id}", headers=other_auth_headers)
    assert response.status_code == 404, "must not confirm that someone else's application exists"

    status_response = client.get(f"/v1/applications/{application_id}/status", headers=other_auth_headers)
    assert status_response.status_code == 404


def test_customer_cannot_download_another_customers_document(client, auth_headers, other_auth_headers):
    from conftest import make_salary_pdf

    upload = client.post(
        "/v1/documents",
        files={"file": ("slip.pdf", make_salary_pdf(), "application/pdf")},
        data={"doc_type": "salary_slip"},
        headers=auth_headers,
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document_id"]

    assert client.get(f"/v1/documents/{document_id}", headers=other_auth_headers).status_code == 404
    assert (
        client.get(f"/v1/documents/{document_id}/signed-url", headers=other_auth_headers).status_code
        == 404
    )
