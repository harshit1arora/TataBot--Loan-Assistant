"""Wire the whole system in one process: agent graph → MCP tools → CRM / OfferMart / core.

Nothing is mocked at the business-logic level. The only substitution is the LLM, and that
is the point of the design: the graph must work identically with a model and without one.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TMP = tempfile.mkdtemp(prefix="agents-tests-")
SECRET = "agents-test-secret-long-enough-1234567890"

os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": f"sqlite:///{TMP}/core.db",
        "STORAGE_DIR": f"{TMP}/storage",
        "JWT_SECRET": SECRET,
        "SERVICE_CLIENT_SECRET": "agents-service-secret-1234",
        "ALLOW_DEMO_AUTH": "true",
        "ALLOWED_ORIGINS": "http://localhost:8080",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "MOCK_CRM_TOKEN": "test-crm-token",
        "MOCK_OFFERMART_TOKEN": "test-offermart-token",
        "MCP_TRANSPORT": "inmemory",
        "LLM_PROVIDER": "rules",
        "AGENT_SERVICE_TOKEN": "test-agent-token",
    }
)

for path in ("core", "mock-crm", "mock-offermart", "mcp-server", "agents", "conversation"):
    sys.path.insert(0, str(ROOT / "services" / path))

import core_service.main as core_main  # noqa: E402
import httpx  # noqa: E402
import mock_crm.main as crm_main  # noqa: E402
import mock_offermart.main as offermart_main  # noqa: E402
import pytest  # noqa: E402
from agents.config import settings  # noqa: E402
from agents.graph import AgentGraph  # noqa: E402
from agents.llm import RuleBasedLLM  # noqa: E402
from agents.mcp_client import McpToolbox  # noqa: E402
from core_service.db import Base as CoreBase  # noqa: E402
from core_service.db import SessionLocal as CoreSession  # noqa: E402
from core_service.db import engine as core_engine  # noqa: E402
from core_service.services import customers as core_customers  # noqa: E402
from mcp_server.upstreams import upstreams  # noqa: E402

AGENT_TOKEN = {"x-service-token": "test-agent-token"}


@pytest.fixture(scope="session", autouse=True)
def _schema():
    CoreBase.metadata.create_all(bind=core_engine)
    with CoreSession() as db:
        core_customers.seed(db)
        db.commit()
    yield


@pytest.fixture(autouse=True)
def _wire_upstreams():
    """Point MCP tools at the three apps through in-memory transports."""
    upstreams.transports = {
        "core": httpx.ASGITransport(app=core_main.app),
        "crm": httpx.ASGITransport(app=crm_main.app),
        "offermart": httpx.ASGITransport(app=offermart_main.app),
    }
    upstreams.settings.__dict__["core_client_secret"] = "agents-service-secret-1234"
    upstreams._core_token = None
    offermart_main.crm_transport = httpx.ASGITransport(app=crm_main.app)
    yield
    upstreams.transports = {}
    offermart_main.crm_transport = None


@pytest.fixture()
def toolbox():
    return McpToolbox(settings)


@pytest.fixture()
def graph(toolbox):
    return AgentGraph(settings, RuleBasedLLM(), toolbox)


@pytest.fixture()
def client(graph):
    """The agent HTTP API, with the graph already built (no lifespan needed)."""
    from agents.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        test_client.app.state.graph = graph
        test_client.app.state.llm_name = "rules"
        yield test_client


def core_customer_count() -> int:
    """How many customers exist in the lending core (to prove agents create nothing)."""
    with CoreSession() as db:
        return len(core_customers.DEMO_CUSTOMERS) + db.query(
            core_customers.Customer
        ).filter(core_customers.Customer.source == "self_registered").count()


def core_http():
    """A sync client for the lending core, in-process."""
    from fastapi.testclient import TestClient

    return TestClient(core_main.app)


def core_customer_token(core, customer_id: str, phone: str) -> dict:
    token = core.post(
        "/auth/token", json={"customer_id": customer_id, "phone": phone}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def core_service_token(core) -> dict:
    token = core.post(
        "/auth/service-token",
        json={"client_id": "conversation-service", "client_secret": "agents-service-secret-1234"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def fresh_customer(income_rupees: int = 120_000, score: int = 768):
    """Register a brand-new customer so a test never inherits another test's documents."""
    import time as _time

    core = core_http()
    phone = "9" + str(int(_time.time() * 1000))[-9:]
    created = core.post(
        "/v1/customers",
        json={
            "name": "Agent Test",
            "phone": phone,
            "email": f"agent{phone[-5:]}@example.com",
            "age": 33,
            "city": "Indore",
            "declared_monthly_income_rupees": income_rupees,
            "declared_credit_score": score,
        },
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["customer_id"]
    return customer_id, core_customer_token(core, customer_id, phone)


def make_salary_pdf(net_pay: int = 92000) -> bytes:
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 760, "Payslip - April 2026")
    pdf.drawString(72, 740, "Employee Name: Rahul Sharma")
    pdf.drawString(72, 720, "Employer: TCS Limited")
    pdf.drawString(72, 700, f"Net Pay: {net_pay}")
    pdf.save()
    return buffer.getvalue()


class FakeLLM:
    """A stand-in model with a scripted answer, for testing the LLM code paths."""

    name = "groq"
    available = True

    def __init__(self, *, route: dict | None = None, prose: str = "") -> None:
        self._route = route
        self._prose = prose
        self.prompts: list[str] = []

    async def complete_json(self, prompt: str, *, system: str = "") -> dict:
        self.prompts.append(prompt)
        if self._route is None:
            raise RuntimeError("no scripted route")
        return self._route

    async def complete(self, prompt: str, *, system: str = "") -> str:
        self.prompts.append(prompt)
        return self._prose
