"""The MCP surface: what it advertises, and what it actually does."""
from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp_server.faq import ENTRIES, search
from mcp_server.server import mcp

pytestmark = pytest.mark.anyio


EXPECTED_TOOLS = {
    "get_customer_profile",
    "get_kyc_status",
    "log_interaction",
    "list_loan_products",
    "get_preapproved_offer",
    "quote_emi",
    "check_eligibility",
    "get_customer_summary",
    "get_document_verification",
    "search_faq",
    "system_status",
}


async def test_the_server_advertises_eleven_typed_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS
    # Every tool carries a description and an input schema, so an agent can choose it.
    for tool in tools:
        assert tool.description
        assert tool.inputSchema["type"] == "object"


async def test_customer_profile_comes_from_the_crm(wired):
    async with Client(mcp) as client:
        result = await client.call_tool("get_customer_profile", {"customer_id": "CUST001"})
    profile = result.data
    assert profile["name"] == "Asha Verma"
    assert profile["credit_score"] == 745
    assert profile["monthly_income_paise"] == 6_000_000


async def test_unknown_customer_becomes_a_tool_error_not_a_crash(wired):
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("get_customer_profile", {"customer_id": "CUST999"})
    assert "crm error (404)" in str(excinfo.value)


async def test_kyc_status(wired):
    async with Client(mcp) as client:
        result = await client.call_tool("get_kyc_status", {"customer_id": "CUST002"})
    assert result.data["phone_verified"] is True


async def test_interaction_is_written_to_the_crm(wired):
    async with Client(mcp) as client:
        created = await client.call_tool(
            "log_interaction",
            {"customer_id": "CUST003", "summary": "Asked about EMI on 5 lakh over 36 months"},
        )
    assert created.data["channel"] == "chat"


async def test_products_come_from_offermart(wired):
    async with Client(mcp) as client:
        result = await client.call_tool("list_loan_products", {})
    codes = {row["code"] for row in result.data["products"]}
    assert codes == {"PL_PRIME", "PL_STANDARD", "PL_FLEX"}


async def test_preapproved_offer_uses_the_crm_profile(wired):
    async with Client(mcp) as client:
        result = await client.call_tool("get_preapproved_offer", {"customer_id": "CUST010"})
    offer = result.data
    assert offer["approved_limit_paise"] == 54_000_000  # 6 × ₹90,000
    assert offer["product"]["code"] == "PL_PRIME"


async def test_quote_emi_matches_the_core_formula(wired):
    async with Client(mcp) as client:
        result = await client.call_tool(
            "quote_emi", {"amount_rupees": 500000, "tenure_months": 36, "product_code": "PL_STANDARD"}
        )
    # 5,00,000 at 12% for 36 months, the same figure the core sanctions.
    assert result.data["emi_paise"] == 1_660_715


async def test_quote_rejects_nonsense_without_calling_an_upstream(wired):
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("quote_emi", {"amount_rupees": -5, "tenure_months": 12})


async def test_eligibility_tool_explains_without_creating_anything(wired):
    async with Client(mcp) as client:
        result = await client.call_tool(
            "check_eligibility",
            {"customer_id": "CUST001", "amount_rupees": 200000, "tenure_months": 36},
        )
        summary = await client.call_tool("get_customer_summary", {"customer_id": "CUST001"})

    assert result.data["outcome"] == "approve"
    assert result.data["reason_codes"] == ["within_pre_approved_limit"]
    assert summary.data["pre_approved_limit_paise"] == 30_000_000
    assert "phone" not in summary.data, "the agent never needs contact details"


async def test_eligibility_tool_reports_the_document_path(wired):
    async with Client(mcp) as client:
        result = await client.call_tool(
            "check_eligibility",
            {"customer_id": "CUST001", "amount_rupees": 500000, "tenure_months": 36},
        )
    assert result.data["outcome"] == "require_document"


async def test_eligibility_tool_surfaces_a_policy_refusal(wired):
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "check_eligibility",
                {"customer_id": "CUST001", "amount_rupees": 90_000_000, "tenure_months": 36},
            )
    assert "core error (409)" in str(excinfo.value)


async def test_system_status_reports_each_upstream(wired):
    async with Client(mcp) as client:
        result = await client.call_tool("system_status", {})
    assert result.data["upstreams"] == {"core": "ok", "crm": "ok", "offermart": "ok"}


async def test_document_tool_reports_not_found_cleanly(wired):
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("get_document_verification", {"document_id": "nope"})
    assert "core error (404)" in str(excinfo.value)


# --- the FAQ knowledge base -------------------------------------------------
async def test_faq_answers_policy_questions_with_a_source(wired):
    async with Client(mcp) as client:
        result = await client.call_tool("search_faq", {"query": "why do I need a salary slip"})
    top = result.data["results"][0]
    assert top["id"] == "why-document-needed"
    assert top["source"]
    assert "verified" in top["answer"].lower()


@pytest.mark.parametrize(
    "query,expected",
    [
        ("am I eligible for a personal loan", "eligibility-criteria"),
        ("what credit score do I need", "credit-score"),
        ("how is emi calculated", "emi-calculation"),
        ("how do I complain", "contact-support"),
        ("is my data shared", "data-privacy"),
    ],
)
def test_faq_routing(query, expected):
    assert search(query)[0]["id"] == expected


def test_faq_returns_nothing_rather_than_guessing():
    assert search("what is the weather in pune") == []
    assert search("") == []


def test_every_faq_entry_is_attributed():
    for entry in ENTRIES:
        assert entry["source"], f"{entry['id']} has no source"
        assert len(entry["answer"]) > 60


async def test_offer_falls_back_to_the_core_when_the_crm_does_not_know_the_customer(wired):
    """A customer who registered with the lender directly is not in the CRM.

    The offer must still be priced from their real band and income, not from a default
    product — this is the path a self-registered customer takes.
    """
    import time

    from core_service.main import app as core_app
    from fastapi.testclient import TestClient

    core = TestClient(core_app)
    phone = "9" + str(int(time.time() * 1000))[-9:]
    created = core.post(
        "/v1/customers",
        json={
            "name": "New Borrower",
            "phone": phone,
            "email": f"nb{phone[-5:]}@example.com",
            "age": 34,
            "city": "Nashik",
            "declared_monthly_income_rupees": 100_000,
            "declared_credit_score": 745,
        },
    ).json()
    customer_id = created["customer_id"]

    async with Client(mcp) as client:
        result = await client.call_tool("get_preapproved_offer", {"customer_id": customer_id})

    offer = result.data
    assert offer["offer_source"].startswith("core_summary")
    assert offer["approved_limit_paise"] == 60_000_000  # 6 × ₹1,00,000
    assert offer["product"]["code"] == "PL_STANDARD", "745 belongs on the standard product"
    assert offer["product"]["annual_rate_percent"] == 12.0
