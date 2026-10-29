"""Worker behaviour and end-to-end agent flows.

Every figure asserted here is produced by the real tool chain: agent → MCP tool → service.
"""
from __future__ import annotations

import pytest
from agents.graph import AgentGraph
from agents.llm import prose_is_grounded
from agents.workers.eligibility import EligibilityWorker
from conftest import FakeLLM

pytestmark = pytest.mark.anyio


async def _ask(graph, question, customer_id="CUST001", document_id=None):
    return await graph.run(question, customer_id, document_id)


# --- eligibility ------------------------------------------------------------
async def test_eligibility_explains_an_approval(graph):
    result = await _ask(graph, "would I get 2 lakh for 36 months?")
    assert result["route"] == ["eligibility"]
    assert "approvable" in result["answer"].lower() or "approve" in result["answer"].lower()
    assert "16,607" in result["answer"] or "9,964" in result["answer"] or "EMI" in result["answer"]
    decision = result["results"]["eligibility"]["data"]["decision"]
    assert decision["outcome"] == "approve"
    assert decision["reason_codes"] == ["within_pre_approved_limit"]
    assert result["citations"]


async def test_eligibility_explains_the_document_path(graph):
    from conftest import fresh_customer

    # ₹60,000 declared income -> ₹3,60,000 indicative limit, so ₹5 lakh needs a document.
    customer_id, _ = fresh_customer(income_rupees=60_000)
    result = await _ask(graph, "can I get 5 lakh for 36 months?", customer_id)
    decision = result["results"]["eligibility"]["data"]["decision"]
    assert decision["outcome"] == "require_document"
    assert "salary slip" in result["answer"].lower()


async def test_eligibility_explains_a_decline(graph):
    result = await _ask(graph, "am I eligible for 1 lakh", customer_id="CUST004")
    decision = result["results"]["eligibility"]["data"]["decision"]
    assert decision["outcome"] == "reject"
    assert "credit score" in result["answer"].lower()


async def test_eligibility_asks_for_the_amount_when_it_is_missing(graph):
    result = await _ask(graph, "am I eligible for a loan?")
    assert result["needs_input"] == ["amount"]
    assert "what amount" in result["answer"].lower()


async def test_eligibility_without_a_customer_asks_who_they_are(graph):
    result = await _ask(graph, "am I eligible for 2 lakh", customer_id=None)
    assert result["needs_input"] == ["customer"]


# --- interest ---------------------------------------------------------------
async def test_interest_quotes_match_the_core_formula(graph):
    result = await _ask(graph, "what is the emi on 5 lakh for 36 months?")
    quote = result["results"]["interest"]["data"]["quote"]
    # The core's own figure for 5,00,000 at 12% over 36 months.
    assert quote["emi_paise"] == 1_660_715
    assert "16,607" in result["answer"]


async def test_interest_uses_the_customers_product_rate(graph):
    """CUST010 scores 790, so pricing should use the prime product."""
    result = await _ask(graph, "emi on 3 lakh for 24 months", customer_id="CUST010")
    quote = result["results"]["interest"]["data"]["quote"]
    assert quote["product_code"] == "PL_PRIME"
    assert quote["annual_rate_percent"] == 10.99


async def test_interest_needs_an_amount(graph):
    result = await _ask(graph, "what would the emi be?")
    assert result["needs_input"] == ["amount"]


# --- documents --------------------------------------------------------------
async def test_document_worker_explains_requirements(graph):
    from conftest import fresh_customer

    customer_id, _ = fresh_customer()
    result = await _ask(graph, "which documents do I need to upload?", customer_id)
    assert result["route"] == ["document"]
    assert "salary slip" in result["answer"].lower()


async def test_document_worker_reports_a_verified_document(graph):
    """Upload through the core, extract, then ask the document agent about it."""
    from conftest import core_customer_token, core_http, core_service_token, make_salary_pdf

    core = core_http()
    auth = core_customer_token(core, "CUST002", "9810000002")
    uploaded = core.post(
        "/v1/documents",
        files={"file": ("slip.pdf", make_salary_pdf(92000), "application/pdf")},
        data={"doc_type": "salary_slip"},
        headers=auth,
    ).json()
    core.post(
        f"/internal/documents/{uploaded['document_id']}/process",
        headers=core_service_token(core),
    )

    result = await _ask(
        graph, f"what is the status of document {uploaded['document_id']}", "CUST002"
    )
    assert result["route"] == ["document"]
    assert "92,000" in result["answer"]
    assert result["results"]["document"]["data"]["requires_review"] is False


# --- FAQ --------------------------------------------------------------------
async def test_faq_answers_with_a_source(graph):
    result = await _ask(graph, "is my data shared with anyone?")
    assert result["route"] == ["faq"]
    assert result["citations"]
    assert "language model" in result["answer"].lower() or "never" in result["answer"].lower()


async def test_faq_refuses_to_improvise(graph):
    result = await _ask(graph, "what is the capital of France?")
    assert result["route"] == ["faq"]
    assert "sourced answer" in result["answer"].lower()


# --- multi-domain -----------------------------------------------------------
async def test_a_two_part_question_runs_two_workers(graph):
    result = await _ask(graph, "can I get 5 lakh and what would the emi be?")
    assert set(result["route"]) == {"eligibility", "interest"}
    assert "Eligibility:" in result["answer"]
    assert "Interest:" in result["answer"]
    assert len(result["results"]) == 2


# --- the guard --------------------------------------------------------------
async def test_a_model_that_invents_a_number_is_overruled(toolbox):
    """The prose is discarded; the deterministic template answers instead."""
    llm = FakeLLM(route={"agents": ["interest"], "reason": "emi"}, prose="Your EMI is ₹1,234.56.")
    graph = AgentGraph(toolbox.settings, llm, toolbox)

    result = await graph.run("emi on 5 lakh for 36 months", "CUST001")
    assert "1,234" not in result["answer"]
    assert "16,607" in result["answer"], "the tool's figure must survive"


async def test_grounded_prose_is_kept(toolbox):
    llm = FakeLLM(
        route={"agents": ["interest"], "reason": "emi"},
        prose="For 5,00,000 over 36 months the EMI works out to 16,607.15 at 12% a year.",
    )
    graph = AgentGraph(toolbox.settings, llm, toolbox)
    result = await graph.run("emi on 5 lakh for 36 months", "CUST001")
    assert result["answer"].startswith("For 5,00,000")


def test_the_guard_itself():
    assert prose_is_grounded("The EMI is 16,607.15", '{"emi": "16607.15"}')
    assert not prose_is_grounded("The EMI is 12,000", '{"emi": "16607.15"}')
    assert not prose_is_grounded("", "{}")


# --- failure behaviour ------------------------------------------------------
async def test_a_tool_outage_is_explained_not_crashed(toolbox):
    from agents.mcp_client import ToolFailure

    async def boom(tool, **kwargs):
        raise ToolFailure(tool, "core error (503): down")

    toolbox.call = boom  # type: ignore[assignment]
    graph = AgentGraph(toolbox.settings, RuleFallback(), toolbox)

    result = await graph.run("am I eligible for 2 lakh", "CUST001")
    assert "try again" in result["answer"].lower() or "couldn't reach" in result["answer"].lower()
    assert result["route"] == ["eligibility"]


class RuleFallback:
    name = "rules"
    available = False

    async def complete(self, prompt, *, system=""):
        raise RuntimeError

    async def complete_json(self, prompt, *, system=""):
        raise RuntimeError


async def test_agents_never_create_an_application(graph):
    from conftest import core_customer_token, core_http

    core = core_http()
    auth = core_customer_token(core, "CUST005", "9810000005")
    before = len(core.get("/v1/applications", headers=auth).json())

    for question in (
        "am I eligible for 3 lakh for 36 months",
        "emi on 3 lakh for 36 months",
        "which documents do I need",
    ):
        await graph.run(question, "CUST005")

    after = len(core.get("/v1/applications", headers=auth).json())
    assert after == before, "an agent query must not create an application"


async def test_worker_asks_a_direct_question(graph):
    """A worker used directly (not via the graph) still returns the same shape."""
    worker = EligibilityWorker(graph.toolbox, graph.llm)
    result = await worker.run({"question": "can I get 2 lakh", "customer_id": "CUST006"})
    assert "eligibility" in result["results"]
    assert result["results"]["eligibility"]["kind"] == "answer"


# --- presentation -----------------------------------------------------------
def test_indian_money_formatting():
    from agents.formatting import inr, rupees

    assert rupees(500_000) == "₹5,00,000.00"
    assert inr(1_660_715) == "₹16,607.15"
    assert rupees(10_000_000) == "₹1,00,00,000.00"
    assert inr(None) == "—"


def test_reason_codes_read_as_english():
    from agents.formatting import reason_text

    assert reason_text("within_pre_approved_limit") == "within your available limit"
    assert reason_text("emi_exceeds_foir_limit").startswith("the EMI would exceed")
    assert reason_text("something_new") == "something new"


async def test_answers_use_indian_grouping(graph):
    result = await _ask(graph, "can I get 2 lakh for 36 months?")
    assert "₹2,00,000" in result["answer"], result["answer"]
    assert "within your available limit" in result["answer"]


# --- the guard must not punish a model for quoting the loan it was asked about
async def test_model_prose_may_quote_the_requested_amount(toolbox):
    """Regression: the amount was absent from the guard payload, so every answer that
    mentioned the loan was discarded and the template used instead."""
    captured: dict = {}

    class QuotingLLM:
        name = "groq"
        available = True

        async def complete(self, prompt, *, system=""):
            captured["prompt"] = prompt
            return "For a ₹5,00,000 loan over 36 months you need to verify your income first."

        async def complete_json(self, prompt, *, system=""):
            return {"agents": ["eligibility"], "reason": "test"}

    from conftest import fresh_customer

    customer_id, _ = fresh_customer(income_rupees=60_000)
    worker = EligibilityWorker(toolbox, QuotingLLM())
    result = await worker.run({"question": "can I get 5 lakh for 36 months?", "customer_id": customer_id})

    answer = result["results"]["eligibility"]["answer"]
    assert answer.startswith("For a ₹5,00,000 loan"), "grounded prose should be kept"
    assert "amount_rupees" in captured["prompt"], "the request must be in the payload"
    assert "reasons_readable" in captured["prompt"], "internal codes should be labelled for the model"


async def test_model_prose_is_still_rejected_when_it_invents_a_figure(toolbox):
    class LyingLLM:
        name = "groq"
        available = True

        async def complete(self, prompt, *, system=""):
            return "Your EMI would be ₹99,999 per month and you are pre-approved for ₹50,00,000."

        async def complete_json(self, prompt, *, system=""):
            return {"agents": ["eligibility"], "reason": "test"}

    from conftest import fresh_customer

    customer_id, _ = fresh_customer(income_rupees=60_000)
    worker = EligibilityWorker(toolbox, LyingLLM())
    result = await worker.run({"question": "can I get 5 lakh for 36 months?", "customer_id": customer_id})

    answer = result["results"]["eligibility"]["answer"]
    assert "99,999" not in answer
    assert "50,00,000" not in answer
