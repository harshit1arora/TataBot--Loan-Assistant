"""Full stack, one process: chat → orchestrator → LangGraph agents → MCP tools → services.

This is the test that proves the claims end to end. Nothing is stubbed except the LLM
(which is designed to be absent): every number comes from the real policy, the real offer
engine and the real CRM.
"""
from __future__ import annotations

import os
import tempfile

import httpx
import pytest

pytestmark = pytest.mark.anyio

# The conversation service reads DATABASE_URL at import; give it its own file so it does
# not collide with the core service imported by conftest.
_CONV_DB = tempfile.mkdtemp(prefix="conv-e2e-")
os.environ["DATABASE_URL"] = f"sqlite:///{_CONV_DB}/conversation.db"
os.environ["CORE_CLIENT_SECRET"] = "agents-service-secret-1234"   # conversation → core
os.environ["AGENTS_ENABLED"] = "true"
os.environ["AGENTS_SERVICE_TOKEN"] = "test-agent-token"

import conversation_service.main as conv_main  # noqa: E402
from agents.config import settings as agent_settings  # noqa: E402
from agents.graph import AgentGraph  # noqa: E402
from agents.llm import RuleBasedLLM  # noqa: E402
from agents.mcp_client import McpToolbox  # noqa: E402
from conftest import fresh_customer, make_salary_pdf  # noqa: E402
from core_service.main import app as core_app  # noqa: E402


class GraphAgents:
    """Stands in for the HTTP hop to the agent service, calling the real graph instead."""

    def __init__(self, graph: AgentGraph) -> None:
        self.graph = graph

    async def ask(self, question, customer_id, document_id=None):
        result = await self.graph.run(question, customer_id, document_id)
        return {
            "answer": result.get("answer", ""),
            "route": result.get("route", []),
            "citations": result.get("citations", []),
            "needs_input": result.get("needs_input", []),
        }


@pytest.fixture()
def chat():
    """The conversation service, wired to the in-process agent graph."""
    from fastapi.testclient import TestClient

    graph = AgentGraph(agent_settings, RuleBasedLLM(), McpToolbox(agent_settings))
    with TestClient(conv_main.app) as client:
        # The conversation service talks to the core over HTTP; in-process here.
        from conversation_service.clients import CoreClient

        client.app.state.orchestrator.core = CoreClient(
            conv_main.settings, transport=httpx.ASGITransport(app=core_app)
        )
        client.app.state.orchestrator.agents = GraphAgents(graph)
        client.app.state.orchestrator.settings.__dict__["agents_enabled"] = True
        yield client


def _auth(income_rupees: int = 120_000, score: int = 768):
    """A brand-new customer, so each test starts with no documents on file."""
    _customer_id, auth = fresh_customer(income_rupees=income_rupees, score=score)
    return auth


def _say(chat, auth, message, session_id=None):
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    return chat.post("/chat", json=payload, headers=auth).json()


# --- questions are routed to the agents -------------------------------------
async def test_an_eligibility_question_is_answered_by_the_eligibility_agent(chat):
    # ₹60,000 income -> ₹3,60,000 limit, so ₹5 lakh must take the document path.
    auth = _auth(income_rupees=60_000)
    first = _say(chat, auth, "hello")
    session_id = first["session_id"]

    answer = _say(chat, auth, "can I get 5 lakh for 36 months?", session_id)

    assert answer["intent"] == "agents"
    assert answer["agent_route"] == ["eligibility"]
    assert "salary slip" in answer["reply"].lower()
    assert answer["state"] == "awaiting_amount", "a question must not move the workflow"
    assert answer["citations"]


async def test_an_interest_question_quotes_the_core_figure(chat):
    # A 745 score lands on the standard product at 12%, the rate the core also uses.
    auth = _auth(score=745)
    session_id = _say(chat, auth, "hello")["session_id"]

    answer = _say(chat, auth, "what would the EMI be on 5 lakh over 36 months?", session_id)

    assert answer["agent_route"] == ["interest"]
    assert "16,607" in answer["reply"]


async def test_interest_is_priced_at_the_customers_own_product(chat):
    """A 790 score gets the prime product, so the EMI is lower than the standard quote."""
    auth = _auth(score=790)
    session_id = _say(chat, auth, "hello")["session_id"]

    answer = _say(chat, auth, "what would the EMI be on 5 lakh over 36 months?", session_id)

    assert "10.99" in answer["reply"]
    assert "16,366" in answer["reply"], answer["reply"]
    assert "16,607" not in answer["reply"], "must not quote the standard rate to a prime customer"


async def test_a_policy_question_goes_to_the_faq_agent(chat):
    auth = _auth()
    session_id = _say(chat, auth, "hello")["session_id"]

    answer = _say(chat, auth, "is my data shared with the model?", session_id)
    assert answer["agent_route"] == ["faq"]
    assert answer["citations"]


async def test_a_document_question_goes_to_the_document_agent(chat):
    auth = _auth()
    session_id = _say(chat, auth, "hello")["session_id"]

    answer = _say(chat, auth, "which documents do I need to upload?", session_id)
    assert answer["agent_route"] == ["document"]
    assert "salary slip" in answer["reply"].lower()


async def test_a_two_part_question_uses_two_agents(chat):
    auth = _auth()
    session_id = _say(chat, auth, "hello")["session_id"]

    answer = _say(chat, auth, "can I get 5 lakh and what emi would that be?", session_id)
    assert set(answer["agent_route"]) == {"eligibility", "interest"}
    assert "Eligibility:" in answer["reply"] and "Interest:" in answer["reply"]


# --- and the deterministic flow still works ---------------------------------
async def test_the_application_flow_is_untouched_by_delegation(chat):
    auth = _auth(income_rupees=60_000)
    session_id = _say(chat, auth, "hello")["session_id"]

    # A question first...
    _say(chat, auth, "what documents do I need?", session_id)

    # ...then a statement, which must start a real application.
    applied = _say(chat, auth, "I need 5 lakh for 36 months", session_id)
    assert applied["state"] == "awaiting_document"
    assert applied["application"]["decision"]["outcome"] == "require_document"

    # ...and an upload, which must complete it through the same policy.
    uploaded = chat.post(
        f"/sessions/{session_id}/documents",
        files={"file": ("slip.pdf", make_salary_pdf(85000), "application/pdf")},
        data={"doc_type": "salary_slip"},
        headers=auth,
    ).json()
    assert uploaded["state"] == "sanctioned"
    assert uploaded["application"]["decision"]["reason_codes"] == ["emi_within_foir"]


async def test_the_routing_trace_shows_the_whole_route(chat):
    auth = _auth()
    session_id = _say(chat, auth, "hello")["session_id"]
    _say(chat, auth, "am I eligible for 2 lakh?", session_id)
    _say(chat, auth, "I need 2 lakh for 24 months", session_id)

    trace = chat.get(f"/sessions/{session_id}/trace", headers=auth).json()
    events = [step["event"] for step in trace["steps"]]
    # greeting, the question (no transition), then the application decision
    assert events == ["greeting", "outcome_approved"]
    assert trace["state"] == "sanctioned"


async def test_a_statement_is_never_routed_to_the_agents(chat):
    auth = _auth()
    session_id = _say(chat, auth, "hello")["session_id"]
    answer = _say(chat, auth, "I need 1 lakh for 12 months", session_id)
    assert answer["intent"] is None
    assert answer["agent_route"] == []


async def test_agent_failure_degrades_to_an_honest_reply(chat):
    from conversation_service.agents_client import AgentsUnavailable

    class Broken:
        async def ask(self, *args, **kwargs):
            raise AgentsUnavailable("down")

    chat.app.state.orchestrator.agents = Broken()
    auth = _auth()
    session_id = _say(chat, auth, "hello")["session_id"]

    answer = _say(chat, auth, "am I eligible for 2 lakh?", session_id)
    assert answer["intent"] == "agents_unavailable"
    assert "won't guess" in answer["reply"].lower()
    assert answer["state"] == "awaiting_amount"
