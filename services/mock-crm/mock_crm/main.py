"""MockCRM HTTP service.

Service-to-service only: every /v1 route requires the shared service token, because this
holds customer PII and must never be reachable from a browser.
"""
from __future__ import annotations

import hmac
import os
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .store import store

SERVICE_TOKEN = os.environ.get("MOCK_CRM_TOKEN", "mock-crm-token-change-me")

app = FastAPI(title="MockCRM", version="1.0.0", description="Stand-in CRM: profiles, KYC, interactions.")


def require_service_token(x_service_token: Annotated[str | None, Header()] = None) -> None:
    if not x_service_token or not hmac.compare_digest(x_service_token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="service token required")


class KycVerifyRequest(BaseModel):
    field: Literal["phone_verified", "address_verified", "pan_verified"]
    value: bool


class InteractionRequest(BaseModel):
    channel: Literal["chat", "phone", "email", "branch"] = "chat"
    summary: Annotated[str, Field(min_length=3, max_length=500)]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mock-crm", "customers": len(store.customers)}


@app.get("/v1/customers", dependencies=[Depends(require_service_token)])
def list_customers() -> list[dict]:
    return store.list_customers()


@app.get("/v1/customers/{customer_id}", dependencies=[Depends(require_service_token)])
def get_customer(customer_id: str) -> dict:
    customer = store.get(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return customer


@app.get("/v1/customers/{customer_id}/kyc", dependencies=[Depends(require_service_token)])
def get_kyc(customer_id: str) -> dict:
    customer = store.get(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return {"customer_id": customer_id, **customer["kyc"]}


@app.post("/v1/customers/{customer_id}/kyc/verify", dependencies=[Depends(require_service_token)])
def verify_kyc(customer_id: str, payload: KycVerifyRequest) -> dict:
    customer = store.set_kyc(customer_id, payload.field, payload.value)
    if customer is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return {"customer_id": customer_id, **customer["kyc"]}


@app.post("/v1/customers/{customer_id}/interactions", dependencies=[Depends(require_service_token)])
def add_interaction(customer_id: str, payload: InteractionRequest) -> dict:
    record = store.add_interaction(customer_id, payload.channel, payload.summary)
    if record is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return {"id": record.id, "customer_id": record.customer_id, "channel": record.channel,
            "summary": record.summary, "created_at": record.created_at}


@app.get("/v1/customers/{customer_id}/interactions", dependencies=[Depends(require_service_token)])
def list_interactions(customer_id: str) -> list[dict]:
    if store.get(customer_id) is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return [
        {"id": row.id, "channel": row.channel, "summary": row.summary, "created_at": row.created_at}
        for row in store.list_interactions(customer_id)
    ]
