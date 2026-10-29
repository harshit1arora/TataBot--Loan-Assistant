"""OfferMart HTTP service: catalogue, offers and pricing."""
from __future__ import annotations

import hmac
import os
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .pricing import PRODUCTS, build_offer, build_offer_for_band, compute_emi_paise, quote

SERVICE_TOKEN = os.environ.get("MOCK_OFFERMART_TOKEN", "mock-offermart-token-change-me")
CRM_BASE_URL = os.environ.get("CRM_BASE_URL", "http://localhost:8002")
CRM_TOKEN = os.environ.get("MOCK_CRM_TOKEN", "mock-crm-token-change-me")

app = FastAPI(title="OfferMart", version="1.0.0", description="Stand-in offer and pricing engine.")

# Injected in tests so the CRM hop can be exercised without a network socket.
crm_transport: httpx.AsyncBaseTransport | None = None


def require_service_token(x_service_token: Annotated[str | None, Header()] = None) -> None:
    if not x_service_token or not hmac.compare_digest(x_service_token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="service token required")


class EvaluateRequest(BaseModel):
    """An offer for a profile the caller already holds (no CRM lookup)."""

    credit_score_band: Literal["excellent", "good", "fair"]
    monthly_income_paise: Annotated[int, Field(ge=100_000, le=100_000_000)]
    customer_id: str | None = None


class QuoteRequest(BaseModel):
    principal_paise: Annotated[int, Field(gt=0, le=500_000_000)]
    tenure_months: Annotated[int, Field(ge=6, le=60)]
    product_code: str | None = None


async def _fetch_customer(customer_id: str) -> dict:
    """OfferMart asks the CRM for the profile rather than keeping its own copy."""
    async with httpx.AsyncClient(
        base_url=CRM_BASE_URL, timeout=3.0, transport=crm_transport
    ) as client:
        response = await client.get(
            f"/v1/customers/{customer_id}", headers={"x-service-token": CRM_TOKEN}
        )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="customer not found in CRM")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"CRM refused the lookup (HTTP {response.status_code})"
        )
    return response.json()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mock-offermart", "products": len(PRODUCTS)}


@app.get("/v1/products", dependencies=[Depends(require_service_token)])
def list_products() -> list[dict]:
    return PRODUCTS


@app.get("/v1/offers/{customer_id}", dependencies=[Depends(require_service_token)])
async def get_offer(customer_id: str) -> dict:
    customer = await _fetch_customer(customer_id)
    offer = build_offer(customer)
    if offer is None:
        raise HTTPException(status_code=422, detail="no product available for this credit profile")
    return offer


@app.post("/v1/offers/evaluate", dependencies=[Depends(require_service_token)])
def evaluate_offer(payload: EvaluateRequest) -> dict:
    offer = build_offer_for_band(
        payload.credit_score_band, payload.monthly_income_paise, payload.customer_id
    )
    if offer is None:
        raise HTTPException(status_code=422, detail="no product available for this credit band")
    return offer


@app.post("/v1/price", dependencies=[Depends(require_service_token)])
def price(payload: QuoteRequest) -> dict:
    return quote(payload.principal_paise, payload.tenure_months, payload.product_code)


@app.post("/v1/emi", dependencies=[Depends(require_service_token)])
def emi(payload: QuoteRequest) -> dict:
    """EMI for a specific product, without the offer wrapper."""
    result = quote(payload.principal_paise, payload.tenure_months, payload.product_code)
    return {
        "emi_paise": result["emi_paise"],
        "annual_rate_percent": result["annual_rate_percent"],
        "total_payable_paise": result["total_payable_paise"],
        "total_interest_paise": result["total_interest_paise"],
    }


__all__ = ["app", "compute_emi_paise"]
