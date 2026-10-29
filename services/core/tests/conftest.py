"""Test harness.

Environment is set before the application imports, so settings, the engine and the
storage root all point at a throwaway location.
"""
from __future__ import annotations

import os
import tempfile

# ONNX Runtime (used by RapidOCR) spawns a thread per core by default, which starves the
# test process on small machines. One thread is plenty for a payslip.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("ORT_NUM_THREADS", "1")

_TMP = tempfile.mkdtemp(prefix="tatabot-core-tests-")
os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": f"sqlite:///{_TMP}/test.db",
        "STORAGE_DIR": f"{_TMP}/storage",
        "JWT_SECRET": "test-secret-value-that-is-long-enough-1234567890",
        "SERVICE_CLIENT_SECRET": "test-service-secret",
        "ALLOW_DEMO_AUTH": "true",
        "ALLOWED_ORIGINS": "http://localhost:8080",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "MIN_EXTRACTION_CONFIDENCE": "0.75",
    }
)

import pytest  # noqa: E402
from core_service.db import Base, SessionLocal, engine  # noqa: E402
from core_service.main import app  # noqa: E402
from core_service.ratelimit import reset as reset_rate_limit  # noqa: E402
from core_service.services import customers as customer_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

CUSTOMER = {"customer_id": "CUST001", "phone": "9810000001"}
OTHER_CUSTOMER = {"customer_id": "CUST002", "phone": "9810000002"}


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        customer_service.seed(db)
        db.commit()
    yield


@pytest.fixture()
def client():
    reset_rate_limit()
    with TestClient(app) as test_client:
        yield test_client


def _token(client, creds=CUSTOMER) -> str:
    response = client.post("/auth/token", json=creds)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def auth_headers(client):
    return {"Authorization": f"Bearer {_token(client)}"}


@pytest.fixture()
def other_auth_headers(client):
    return {"Authorization": f"Bearer {_token(client, OTHER_CUSTOMER)}"}


def token_for(client, customer_id: str, phone: str) -> dict:
    response = client.post("/auth/token", json={"customer_id": customer_id, "phone": phone})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def process_extraction_jobs() -> None:
    """Drain the extraction queue (what the worker process does in production)."""
    from core_service.config import get_settings
    from core_service.db import SessionLocal
    from core_service.services import documents as document_service
    from core_service.storage import LocalObjectStore

    settings = get_settings()
    store = LocalObjectStore(settings)
    with SessionLocal() as db:
        while document_service.process_next_job(db, settings=settings, store=store) is not None:
            db.commit()
        db.commit()


@pytest.fixture()
def service_headers(client):
    response = client.post(
        "/auth/service-token",
        json={"client_id": "conversation-service", "client_secret": "test-service-secret"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_salary_pdf(net_pay: int = 85000) -> bytes:
    """A real PDF with a text layer, so extraction has something honest to read."""
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 760, "Payslip - March 2026")
    pdf.drawString(72, 740, "Employee Name: Test Employee")
    pdf.drawString(72, 720, "Employer: Example Technologies Pvt Ltd")
    pdf.drawString(72, 700, f"Net Pay: {net_pay}")
    pdf.save()
    return buffer.getvalue()
