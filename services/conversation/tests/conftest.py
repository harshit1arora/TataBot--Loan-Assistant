"""Test harness.

Both services run in one process: the core app is driven through an in-memory ASGI
transport, so these are real end-to-end tests with no network and no mocks of the
business logic.
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="tatabot-conv-tests-")
_JWT_SECRET = "test-secret-value-that-is-long-enough-1234567890"

# --- core service environment (read at import) --------------------------------
os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": f"sqlite:///{_TMP}/core.db",
        "STORAGE_DIR": f"{_TMP}/storage",
        "JWT_SECRET": _JWT_SECRET,
        "SERVICE_CLIENT_SECRET": "test-service-secret",
        "ALLOW_DEMO_AUTH": "true",
        "ALLOWED_ORIGINS": "http://localhost:8080",
        "RATE_LIMIT_PER_MINUTE": "100000",
    }
)

import core_service.main as core_main  # noqa: E402
import pytest  # noqa: E402
from core_service.db import Base as CoreBase  # noqa: E402
from core_service.db import SessionLocal as CoreSessionLocal  # noqa: E402
from core_service.db import engine as core_engine  # noqa: E402
from core_service.services import customers as core_customers  # noqa: E402

# --- conversation service environment ----------------------------------------
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_TMP}/conversation.db",
        "JWT_SECRET": _JWT_SECRET,
        "JWT_ISSUER": "core-service",
        "JWT_AUDIENCE": "tatabot-api",
        "CORE_BASE_URL": "http://core.test",
        "CORE_CLIENT_ID": "conversation-service",
        "CORE_CLIENT_SECRET": "test-service-secret",
        "LLM_ENABLED": "false",
        "ALLOWED_ORIGINS": "http://localhost:8080",
        "RATE_LIMIT_PER_MINUTE": "100000",
    }
)

import conversation_service.main as conv_main  # noqa: E402
import httpx  # noqa: E402
from conversation_service import ratelimit as conv_ratelimit  # noqa: E402
from conversation_service.clients import CoreClient  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

CUSTOMER = ("CUST001", "9810000001")
OTHER = ("CUST002", "9810000002")


@pytest.fixture(scope="session", autouse=True)
def _core_schema():
    CoreBase.metadata.create_all(bind=core_engine)
    with CoreSessionLocal() as db:
        core_customers.seed(db)
        db.commit()
    yield


@pytest.fixture()
def core_client():
    with TestClient(core_main.app) as client:
        yield client


@pytest.fixture()
def client(core_client):
    """Conversation service wired to the in-process core app."""
    conv_ratelimit.reset()
    with TestClient(conv_main.app) as test_client:
        test_client.app.state.orchestrator.core = CoreClient(
            conv_main.settings,
            transport=httpx.ASGITransport(app=core_main.app),
        )
        yield test_client


def _token(core_client, customer=CUSTOMER) -> str:
    response = core_client.post(
        "/auth/token", json={"customer_id": customer[0], "phone": customer[1]}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def auth(core_client):
    return {"Authorization": f"Bearer {_token(core_client)}"}


@pytest.fixture()
def other_auth(core_client):
    return {"Authorization": f"Bearer {_token(core_client, OTHER)}"}


def fresh_customer(core_client, *, income: int = 120000, score: int = 768) -> tuple[str, dict]:
    """Register a brand-new customer and return (customer_id, auth headers).

    Tests that depend on "no documents on file" use this instead of a seeded customer,
    so one test's upload cannot change another test's decision.
    """
    import time

    phone = "9" + str(int(time.time() * 1000))[-9:]
    created = core_client.post(
        "/v1/customers",
        json={
            "name": "Trace Test",
            "phone": phone,
            "email": f"trace{phone[-5:]}@example.com",
            "age": 33,
            "city": "Indore",
            "declared_monthly_income_rupees": income,
            "declared_credit_score": score,
        },
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["customer_id"]
    return customer_id, {"Authorization": f"Bearer {_token(core_client, (customer_id, phone))}"}


def make_salary_pdf(net_pay: int = 85000) -> bytes:
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
