"""Drive the real MCP server in-memory against the real upstream apps.

`Client(mcp)` speaks the actual MCP protocol to the server object, so these tests exercise
tool listing, schema validation and dispatch — not just the Python functions.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TMP = tempfile.mkdtemp(prefix="mcp-tests-")
SECRET = "mcp-test-secret-long-enough-1234567890"

os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": f"sqlite:///{TMP}/core.db",
        "STORAGE_DIR": f"{TMP}/storage",
        "JWT_SECRET": SECRET,
        "SERVICE_CLIENT_SECRET": "mcp-service-secret-1234",
        "ALLOW_DEMO_AUTH": "true",
        "ALLOWED_ORIGINS": "http://localhost:8080",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "MOCK_CRM_TOKEN": "test-crm-token",
        "MOCK_OFFERMART_TOKEN": "test-offermart-token",
    }
)

for path in ("core", "mock-crm", "mock-offermart", "mcp-server"):
    sys.path.insert(0, str(ROOT / "services" / path))

import core_service.main as core_main  # noqa: E402
import httpx  # noqa: E402
import mock_crm.main as crm_main  # noqa: E402
import mock_offermart.main as offermart_main  # noqa: E402
import pytest  # noqa: E402
from core_service.db import Base as CoreBase  # noqa: E402
from core_service.db import SessionLocal as CoreSession  # noqa: E402
from core_service.db import engine as core_engine  # noqa: E402
from core_service.services import customers as core_customers  # noqa: E402
from mcp_server.upstreams import upstreams  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    CoreBase.metadata.create_all(bind=core_engine)
    with CoreSession() as db:
        core_customers.seed(db)
        db.commit()
    yield


@pytest.fixture()
def wired():
    """Point the tool server at the three apps through in-memory transports."""
    upstreams.transports = {
        "core": httpx.ASGITransport(app=core_main.app),
        "crm": httpx.ASGITransport(app=crm_main.app),
        "offermart": httpx.ASGITransport(app=offermart_main.app),
    }
    upstreams.settings.__dict__["core_client_secret"] = "mcp-service-secret-1234"
    upstreams._core_token = None
    offermart_main.crm_transport = httpx.ASGITransport(app=crm_main.app)
    yield upstreams
    upstreams.transports = {}
    offermart_main.crm_transport = None
