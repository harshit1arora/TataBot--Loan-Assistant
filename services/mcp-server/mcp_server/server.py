"""The MCP tool surface.

Eleven tools across three upstreams plus a local knowledge base. Each tool returns plain
JSON so an agent can reason over it, and each failure is raised as a tool error with the
upstream and status attached — the agent sees "crm returned 404", not a stack trace.
"""
from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .faq import ENTRIES, search
from .upstreams import UpstreamError, upstreams

mcp = FastMCP(
    name="tatabot-loan-tools",
    instructions=(
        "Tools for a personal-loan origination system: customer profiles and KYC from the CRM, "
        "offers and pricing from OfferMart, eligibility and document state from the lending core, "
        "and a policy FAQ. Eligibility tools are read-only: they explain what the policy would "
        "decide and never create an application."
    ),
)


def _tool_error(exc: UpstreamError) -> ToolError:
    return ToolError(f"{exc.service} error ({exc.status}): {exc.detail}")


# --- CRM --------------------------------------------------------------------
@mcp.tool
async def get_customer_profile(customer_id: str) -> dict:
    """Fetch a customer's CRM profile: name, city, employment, monthly income, credit score."""
    try:
        customer = await upstreams.crm_get_customer(customer_id)
    except UpstreamError as exc:
        raise _tool_error(exc) from exc
    return {
        "customer_id": customer["id"],
        "name": customer["name"],
        "city": customer["city"],
        "employment": customer["employment"],
        "employer": customer["employer"],
        "monthly_income_paise": customer["monthly_income_paise"],
        "credit_score": customer["credit_score"],
    }


@mcp.tool
async def get_kyc_status(customer_id: str) -> dict:
    """KYC verification state held in the CRM (phone, address, PAN)."""
    try:
        return await upstreams.crm_kyc(customer_id)
    except UpstreamError as exc:
        raise _tool_error(exc) from exc


@mcp.tool
async def log_interaction(customer_id: str, summary: str, channel: str = "chat") -> dict:
    """Record what the customer asked about, against their CRM record."""
    try:
        return await upstreams.crm_log_interaction(customer_id, summary, channel)
    except UpstreamError as exc:
        raise _tool_error(exc) from exc


# --- OfferMart --------------------------------------------------------------
@mcp.tool
async def list_loan_products() -> dict:
    """The loan product catalogue: rate, score floor, amount band and tenure options."""
    try:
        products = await upstreams.offermart_products()
    except UpstreamError as exc:
        raise _tool_error(exc) from exc
    return {"products": products, "count": len(products)}


@mcp.tool
async def get_preapproved_offer(customer_id: str) -> dict:
    """The indicative offer for a customer: limit, best product, rate and alternatives.

    Prefers the CRM-backed lookup. If the customer is not in the CRM — someone who
    registered with the lender directly — it evaluates the offer from the core's own
    summary instead of failing or guessing a product.
    """
    try:
        return await upstreams.offermart_offer(customer_id)
    except UpstreamError as exc:
        if exc.status != 404:
            raise _tool_error(exc) from exc

    try:
        summary = await upstreams.core_summary(customer_id)
        offer = await upstreams.offermart_evaluate(
            summary["credit_score_band"], summary["declared_salary_paise"], customer_id
        )
    except UpstreamError as exc:
        raise _tool_error(exc) from exc

    offer["offer_source"] = "core_summary (customer not in CRM)"
    return offer


@mcp.tool
async def quote_emi(amount_rupees: int, tenure_months: int, product_code: str | None = None) -> dict:
    """Price a loan: EMI, total payable and total interest for an amount and tenure."""
    if amount_rupees <= 0 or tenure_months <= 0:
        raise ToolError("amount_rupees and tenure_months must be positive")
    try:
        return await upstreams.offermart_quote(amount_rupees * 100, tenure_months, product_code)
    except UpstreamError as exc:
        raise _tool_error(exc) from exc


# --- lending core -----------------------------------------------------------
@mcp.tool
async def check_eligibility(customer_id: str, amount_rupees: int, tenure_months: int) -> dict:
    """Run the credit policy read-only and return the outcome, reason codes and EMI.

    This explains what would happen; it does not create an application.
    """
    try:
        decision = await upstreams.core_eligibility(customer_id, amount_rupees, tenure_months)
    except UpstreamError as exc:
        raise _tool_error(exc) from exc
    return {
        "outcome": decision["outcome"],
        "reason_codes": decision["reason_codes"],
        "emi_paise": decision["emi_paise"],
        "interest_rate_percent": decision["interest_rate_percent"],
        "policy_version": decision["policy_version"],
    }


@mcp.tool
async def get_customer_summary(customer_id: str) -> dict:
    """Policy-relevant facts: score band, limit and provenance, verified income. No contact details."""
    try:
        return await upstreams.core_summary(customer_id)
    except UpstreamError as exc:
        raise _tool_error(exc) from exc


@mcp.tool
async def get_document_verification(document_id: str) -> dict:
    """Verification state of an uploaded document: status, confidence, verified income."""
    try:
        return await upstreams.core_document(document_id)
    except UpstreamError as exc:
        raise _tool_error(exc) from exc


# --- local knowledge --------------------------------------------------------
@mcp.tool
async def search_faq(query: str, limit: int = 3) -> dict:
    """Search the policy and process FAQ. Returns answers with the source of each claim."""
    results = search(query, limit=limit)
    return {"query": query, "results": results, "total_entries": len(ENTRIES)}


@mcp.tool
async def system_status() -> dict:
    """Which upstreams are reachable right now. Useful before blaming a tool for a failure."""
    checks: dict[str, str] = {}
    for name, base_url, client_key in (
        ("core", upstreams.settings.core_base_url, "core"),
        ("crm", upstreams.settings.crm_base_url, "crm"),
        ("offermart", upstreams.settings.offermart_base_url, "offermart"),
    ):
        try:
            async with upstreams._client(client_key, base_url) as client:  # noqa: SLF001
                response = await client.get("/health")
            checks[name] = "ok" if response.status_code == 200 else f"http_{response.status_code}"
        except Exception:  # noqa: BLE001 - a status tool must never raise
            checks[name] = "unreachable"
    return {"upstreams": checks, "tools": 11}
