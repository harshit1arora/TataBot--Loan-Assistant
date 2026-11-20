from concurrent.futures import ThreadPoolExecutor

from core_service.config import get_settings
from core_service.db import SessionLocal
from core_service.models import PilotQuote


def test_quote_ownership_reprice_and_acceptance(
    client, auth_headers, other_auth_headers, monkeypatch
):
    payload = {"scenarios": [{"amount_rupees": 45000, "tenure_months": 24}]}
    old = client.post("/v1/quotes/compare", json=payload, headers=auth_headers).json()[0]
    path = "/v1/quotes/" + old["quote_id"] + "/accept"
    assert client.post(path, headers=other_auth_headers).status_code == 404
    monkeypatch.setattr(get_settings(), "annual_rate_percent", 14.0)
    changed = client.post(path, headers=auth_headers).json()
    assert changed["confirmation_required"]
    assert changed["replacement"]["emi_paise"] > changed["previous"]["emi_paise"]
    with SessionLocal() as db:
        assert db.get(PilotQuote, old["quote_id"]).application_id is None
    accept = "/v1/quotes/" + changed["replacement"]["quote_id"] + "/accept"
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(
            pool.map(
                lambda _: client.post(accept, headers=auth_headers).json()["application"][
                    "application_id"
                ],
                range(2),
            )
        )
    assert len(set(ids)) == 1


def test_expired_quote_needs_confirmation(client, auth_headers):
    quote = client.post(
        "/v1/quotes", json={"amount_rupees": 20000, "tenure_months": 12}, headers=auth_headers
    ).json()
    with SessionLocal.begin() as db:
        db.get(PilotQuote, quote["quote_id"]).expires_at = 1
    result = client.post("/v1/quotes/" + quote["quote_id"] + "/accept", headers=auth_headers).json()
    assert result["reason"] == "Quote expired"
    assert result["previous"]["quote_id"] != result["replacement"]["quote_id"]


def test_application_retry_is_atomic_and_rejects_changed_terms(client, auth_headers):
    headers = {**auth_headers, "Idempotency-Key": "pilot-concurrent"}

    def submit(_):
        return client.post(
            "/v1/applications",
            headers=headers,
            json={"requested_amount_rupees": 24000, "tenure_months": 12},
        ).json()["application_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(submit, range(2)))) == 1
    changed = client.post(
        "/v1/applications",
        headers=headers,
        json={"requested_amount_rupees": 23000, "tenure_months": 12},
    )
    assert changed.status_code == 409


def test_referral_replacement_then_confirmation(client, auth_headers, monkeypatch):
    import secrets

    from conftest import make_salary_pdf, token_for
    from core_service.main import app
    from core_service.models import Delivery, Document
    from core_service.routers.identity import identity
    from core_service.services.notifications import schedule_escalations
    from sqlalchemy import select

    phone = "9" + str(secrets.randbelow(10**9)).zfill(9)
    created = client.post(
        "/v1/customers",
        json={
            "name": "Review case",
            "age": 34,
            "phone": phone,
            "email": "review@example.test",
            "city": "Pune",
            "declared_monthly_income_rupees": 60000,
            "declared_credit_score": 745,
        },
    ).json()
    headers = token_for(client, created["customer_id"], phone)
    app_id = client.post(
        "/v1/applications",
        headers=headers,
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
    ).json()["application_id"]
    monkeypatch.setenv("OIDC_REVIEWER_SUBJECTS", "reviewer-A")
    monkeypatch.setenv("ESCALATION_EMAIL", "staff@example.test")
    monkeypatch.setenv("REVIEW_ESCALATION_SECONDS", "0")
    app.dependency_overrides[identity] = lambda: {"sub": "reviewer-A"}
    try:
        for action in ("replace", "confirm"):
            doc_id = client.post(
                "/v1/documents",
                headers=headers,
                data={"doc_type": "salary_slip", "application_id": app_id},
                files={"file": ("pay.pdf", make_salary_pdf(85000), "application/pdf")},
            ).json()["document_id"]
            # This test isolates adjudication; company_demo exercises actual extraction.
            with SessionLocal.begin() as db:
                doc = db.get(Document, doc_id)
                doc.status = "extracted"
                doc.requires_review = True
                doc.extracted_fields = {"monthly_income_paise": 8500000}
            with SessionLocal.begin() as db:
                schedule_escalations(db)
                schedule_escalations(db)
                assert (
                    len(
                        list(
                            db.scalars(
                                select(Delivery).where(Delivery.event_key == "review:" + doc_id)
                            )
                        )
                    )
                    == 1
                )
            response = client.post(
                "/v1/reviews/" + doc_id,
                json={"action": action, "reason": "Reviewed the original slip"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["application"]["application_id"] == app_id
            with SessionLocal() as db:
                assert db.scalar(
                    select(Delivery).where(
                        Delivery.category == "customer", Delivery.recipient == "review@example.test"
                    )
                )
            summary = client.get("/v1/applications/" + app_id + "/summary", headers=headers).json()
            if action == "replace":
                assert "replacement" in summary["next_action"]
            else:
                assert summary["income_source"] == "underwriter_verified"
                assert summary["application"]["status"] == "approved"
    finally:
        del app.dependency_overrides[identity]
