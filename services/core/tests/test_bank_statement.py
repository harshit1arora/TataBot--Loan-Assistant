"""Customer mock bank data never counts as independently verified evidence."""

from datetime import UTC, datetime

from conftest import make_salary_pdf, token_for
from core_service.main import app
from core_service.routers.identity import identity


def credits(amount):
    now = datetime.now(UTC)
    current = now.year * 12 + now.month - 1
    rows = []
    for delta in (3, 2, 1):
        n = current - delta
        rows.append(
            {
                "date": f"{n // 12:04d}-{n % 12 + 1:02d}-01",
                "amount_paise": amount,
                "category": "salary",
            }
        )
    return {"consent_version": "bank-assessment-v1", "credits": rows}


def test_mismatch_then_correction_and_review(client, other_auth_headers, monkeypatch):
    from uuid import uuid4

    phone = "9" + str(int(uuid4().hex[:8], 16) % 10**9).zfill(9)
    created = client.post(
        "/v1/customers",
        json={
            "name": "Bank Test",
            "age": 34,
            "phone": phone,
            "email": "bank@example.test",
            "city": "Pune",
            "declared_monthly_income_rupees": 60000,
            "declared_credit_score": 745,
        },
    )
    assert created.status_code == 201, created.text
    headers = token_for(client, created.json()["customer_id"], phone)
    application = client.post(
        "/v1/applications",
        headers=headers,
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
    ).json()
    application_id = application["application_id"]
    path = f"/v1/applications/{application_id}/bank-statement"
    assert client.post(path, headers=other_auth_headers, json=credits(8400000)).status_code == 404
    assert (
        client.post(
            path, headers=headers, json={**credits(8400000), "consent_version": "wrong"}
        ).status_code
        == 422
    )
    assert (
        client.post(path, headers=headers, json=credits(8400000)).json()["status"]
        == "income_missing"
    )
    upload = client.post(
        "/v1/documents",
        headers=headers,
        data={"doc_type": "salary_slip", "application_id": application_id},
        files={"file": ("pay.pdf", make_salary_pdf(85000), "application/pdf")},
    )
    doc_id = upload.json()["document_id"]
    assessed = client.post(
        f"/v1/applications/{application_id}/documents/{doc_id}/assess", headers=headers
    )
    assert assessed.status_code == 200, assessed.text
    assert assessed.json()["requires_review"]
    assert client.get(path, headers=headers).json()["status"] == "mismatch"
    monkeypatch.setenv("OIDC_REVIEWER_SUBJECTS", "bank-reviewer")
    app.dependency_overrides[identity] = lambda: {"sub": "bank-reviewer"}
    try:
        review = "/v1/reviews/" + doc_id
        body = {"action": "correct", "income_rupees": 85000, "reason": "Verified payroll evidence."}
        assert client.post(review, json=body).status_code == 409
        corrected = client.post(path, headers=headers, json=credits(8500000))
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["status"] == "matching"
        decision = client.post(review, json=body)
        assert decision.status_code == 200, decision.text
        summary = client.get(f"/v1/applications/{application_id}/summary", headers=headers).json()
        assert summary["application"]["status"] == "approved"
        assert summary["bank_cross_check"]["status"] == "matching"
        assert summary["bank_cross_check"]["independently_verified"] is False
    finally:
        del app.dependency_overrides[identity]
        from core_service.db import SessionLocal
        from core_service.models import Delivery
        from sqlalchemy import delete

        with SessionLocal.begin() as db:
            db.execute(delete(Delivery).where(Delivery.recipient == "bank@example.test"))


def test_arithmetic_discrepancy_flagged():
    from io import BytesIO

    from core_service.routers.bank_statement import pdf_signals
    from reportlab.pdfgen import canvas

    out = BytesIO()
    pdf = canvas.Canvas(out)
    pdf.drawString(50, 700, "Gross Salary: 100000")
    pdf.drawString(50, 670, "Total Deductions: 20000")
    pdf.drawString(50, 640, "Net Pay: 85000")
    pdf.save()
    assert "payslip_arithmetic_mismatch" in pdf_signals(out.getvalue())


def test_inconsistent_pdf_dates_are_flagged():
    from io import BytesIO

    from core_service.routers.bank_statement import pdf_signals
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_metadata({"/CreationDate": "D:20260102000000Z", "/ModDate": "D:20260101000000Z"})
    output = BytesIO()
    writer.write(output)
    assert "pdf_modification_before_creation" in pdf_signals(output.getvalue())


def test_arithmetic_signal_routes_matching_income_to_review(client):
    from io import BytesIO
    from uuid import uuid4

    from reportlab.pdfgen import canvas

    phone = "9" + str(int(uuid4().hex[:8], 16) % 10**9).zfill(9)
    created = client.post(
        "/v1/customers",
        json={
            "name": "Signal Test",
            "age": 34,
            "phone": phone,
            "email": "signal@example.test",
            "city": "Pune",
            "declared_monthly_income_rupees": 60000,
            "declared_credit_score": 745,
        },
    )
    headers = token_for(client, created.json()["customer_id"], phone)
    application_id = client.post(
        "/v1/applications",
        headers=headers,
        json={"requested_amount_rupees": 500000, "tenure_months": 36},
    ).json()["application_id"]
    path = f"/v1/applications/{application_id}/bank-statement"
    assert client.post(path, headers=headers, json=credits(8500000)).status_code == 200
    out = BytesIO()
    pdf = canvas.Canvas(out)
    pdf.drawString(50, 700, "Gross Salary: 100000")
    pdf.drawString(50, 670, "Total Deductions: 20000")
    pdf.drawString(50, 640, "Net Pay: 85000")
    pdf.save()
    doc_id = client.post(
        "/v1/documents",
        headers=headers,
        data={"application_id": application_id, "doc_type": "salary_slip"},
        files={"file": ("pay.pdf", out.getvalue(), "application/pdf")},
    ).json()["document_id"]
    assessed = client.post(
        f"/v1/applications/{application_id}/documents/{doc_id}/assess", headers=headers
    )
    assert assessed.status_code == 200
    assert assessed.json()["requires_review"]
    check = client.get(path, headers=headers).json()
    assert check["status"] == "matching" and check["two_source_match"]
    assert "payslip_arithmetic_mismatch" in check["signals"]
    summary = client.get(f"/v1/applications/{application_id}/summary", headers=headers).json()
    assert summary["application"]["status"] == "document_required"
    assert summary["bank_cross_check"]["independently_verified"] is False
