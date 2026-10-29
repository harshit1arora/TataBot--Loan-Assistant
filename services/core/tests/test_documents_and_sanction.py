"""P0/P1: document pipeline, verified income, sanction letters, signed URLs.

Each test uses its own customer so the verified-income lookup cannot leak between tests.
"""
from __future__ import annotations

from conftest import make_salary_pdf, process_extraction_jobs, token_for

CUST_A = ("CUST001", "9810000001")  # pre-approved 3,00,000
CUST_B = ("CUST002", "9810000002")  # pre-approved 2,00,000
CUST_C = ("CUST003", "9810000003")  # pre-approved 4,00,000


def _upload(client, headers, data=None, filename="slip.pdf", content_type="application/pdf", doc_type="salary_slip"):
    return client.post(
        "/v1/documents",
        files={"file": (filename, data if data is not None else make_salary_pdf(), content_type)},
        data={"doc_type": doc_type},
        headers=headers,
    )


def test_multipart_upload_works(client, auth_headers):
    """The old build answered 422 here, so the frontend could never upload anything."""
    response = _upload(client, auth_headers)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "stored"


def test_content_type_is_sniffed_not_trusted(client, auth_headers):
    """A .pdf name with non-PDF bytes is refused."""
    response = _upload(client, auth_headers, data=b"PK\x03\x04 not a pdf at all", filename="slip.pdf")
    assert response.status_code == 422


def test_oversized_upload_is_refused(client, auth_headers):
    big = b"%PDF-" + b"0" * (6 * 1024 * 1024)
    response = _upload(client, auth_headers, data=big)
    assert response.status_code == 422


def test_unknown_document_type_is_refused(client, auth_headers):
    response = _upload(client, auth_headers, doc_type="selfie_with_aadhaar")
    assert response.status_code == 422


def test_extraction_populates_verified_income(client):
    headers = token_for(client, *CUST_A)
    document_id = _upload(client, headers, data=make_salary_pdf(85000)).json()["document_id"]
    process_extraction_jobs()

    body = client.get(f"/v1/documents/{document_id}", headers=headers).json()
    assert body["status"] == "extracted"
    assert body["verified_income_paise"] == 8_500_000
    assert body["requires_review"] is False


def test_image_document_is_queued_for_review_not_invented(client, auth_headers):
    """No fabricated numbers: an image with no OCR gets no income and a review flag."""
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    document_id = _upload(client, auth_headers, data=png, filename="slip.png", content_type="image/png").json()[
        "document_id"
    ]
    process_extraction_jobs()
    body = client.get(f"/v1/documents/{document_id}", headers=auth_headers).json()
    assert body["verified_income_paise"] is None
    assert body["requires_review"] is True


def test_document_unlocks_the_above_limit_path(client):
    """With verified income on file, 5,00,000 is assessed on FOIR instead of being blocked."""
    headers = token_for(client, *CUST_A)
    _upload(client, headers, data=make_salary_pdf(85000))
    process_extraction_jobs()

    response = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
        headers=headers,
    )
    decision = response.json()["decision"]
    assert decision["outcome"] == "approve"
    assert decision["reason_codes"] == ["emi_within_foir"]


def test_low_verified_income_is_rejected_on_foir(client):
    headers = token_for(client, *CUST_C)
    _upload(client, headers, data=make_salary_pdf(12000))
    process_extraction_jobs()

    response = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 600000, "tenure_months": 36},
        headers=headers,
    )
    decision = response.json()["decision"]
    assert decision["outcome"] == "reject"
    assert decision["reason_codes"] == ["emi_exceeds_foir_limit"]


def test_signed_url_downloads_and_cannot_be_forged(client):
    headers = token_for(client, *CUST_B)
    document_id = _upload(client, headers).json()["document_id"]
    signed = client.get(f"/v1/documents/{document_id}/signed-url", headers=headers).json()
    assert signed["expires_in"] <= 60
    assert signed["url"].startswith("/download/")

    ok = client.get(signed["url"])
    assert ok.status_code == 200
    assert ok.content.startswith(b"%PDF-")

    body, _signature = signed["url"].rsplit(".", 1)
    forged = f"{body}.{'0' * 64}"
    assert client.get(forged).status_code == 401


def test_sanction_letter_is_idempotent(client, auth_headers):
    application = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 200000, "tenure_months": 36},
        headers=auth_headers,
    ).json()
    application_id = application["application_id"]

    first = client.post(f"/v1/applications/{application_id}/sanction", headers=auth_headers)
    second = client.post(f"/v1/applications/{application_id}/sanction", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json()["document_id"] == second.json()["document_id"], "must not issue two letters"

    status_body = client.get(f"/v1/applications/{application_id}/status", headers=auth_headers).json()
    assert status_body["stage"] == "sanctioned"
    assert status_body["sanction_document_id"] == first.json()["document_id"]


def test_rejected_application_cannot_be_sanctioned(client, auth_headers):
    application = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 900000, "tenure_months": 36},
        headers=auth_headers,
    ).json()
    assert application["decision"]["outcome"] == "reject"
    response = client.post(f"/v1/applications/{application['application_id']}/sanction", headers=auth_headers)
    assert response.status_code == 409


def test_pending_document_application_cannot_be_sanctioned(client):
    headers = token_for(client, "CUST006", "9810000006")  # pre-approved 3,50,000, no documents
    application = client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
        headers=headers,
    ).json()
    assert application["decision"]["outcome"] == "require_document"
    response = client.post(f"/v1/applications/{application['application_id']}/sanction", headers=headers)
    assert response.status_code == 409
