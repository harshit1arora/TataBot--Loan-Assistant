"""HTTP clients for the upstream services.

The core service needs a service token, which is fetched once and cached until it nears
expiry. Tests inject an httpx transport per upstream so the tools can be exercised against
the real applications in-process.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from .config import Settings
from .config import settings as default_settings


class UpstreamError(RuntimeError):
    """An upstream refused or failed. Tools surface this as a clean tool error."""

    def __init__(self, service: str, status: int, detail: str) -> None:
        self.service = service
        self.status = status
        self.detail = detail
        super().__init__(f"{service} returned {status}: {detail}")


@dataclass
class Upstreams:
    settings: Settings = field(default_factory=lambda: default_settings)
    # service name -> transport, injected in tests
    transports: dict[str, httpx.AsyncBaseTransport] = field(default_factory=dict)
    _core_token: str | None = None
    _core_token_expires: float = 0.0

    def _client(self, service: str, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(self.settings.timeout_seconds),
            transport=self.transports.get(service),
            headers={"user-agent": "tatabot-mcp/1.0"},
        )

    async def _core_service_token(self) -> str:
        if self._core_token and time.monotonic() < self._core_token_expires - 5:
            return self._core_token
        async with self._client("core", self.settings.core_base_url) as client:
            response = await client.post(
                "/auth/service-token",
                json={
                    "client_id": self.settings.core_client_id,
                    "client_secret": self.settings.core_client_secret,
                },
            )
        if response.status_code != 200:
            raise UpstreamError("core", response.status_code, "service token refused")
        body = response.json()
        self._core_token = body["access_token"]
        self._core_token_expires = time.monotonic() + body["expires_in"]
        return self._core_token

    async def _call(
        self,
        service: str,
        base_url: str,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> Any:
        async with self._client(service, base_url) as client:
            response = await client.request(method, path, json=json, headers=headers or {})
        if response.status_code >= 400:
            detail = "request failed"
            try:
                payload = response.json()
                detail = payload.get("error", {}).get("message") or payload.get("detail") or detail
            except Exception:  # noqa: BLE001 - non-JSON error body
                detail = response.text[:120] or detail
            raise UpstreamError(service, response.status_code, str(detail)[:200])
        return response.json()

    # --- MockCRM ---------------------------------------------------------
    async def crm_get_customer(self, customer_id: str) -> dict:
        return cast(dict, await self._call(
            "crm",
            self.settings.crm_base_url,
            "GET",
            f"/v1/customers/{customer_id}",
            headers={"x-service-token": self.settings.crm_token},
        ))

    async def crm_kyc(self, customer_id: str) -> dict:
        return await self._call(
            "crm",
            self.settings.crm_base_url,
            "GET",
            f"/v1/customers/{customer_id}/kyc",
            headers={"x-service-token": self.settings.crm_token},
        )

    async def crm_log_interaction(self, customer_id: str, summary: str, channel: str) -> dict:
        return await self._call(
            "crm",
            self.settings.crm_base_url,
            "POST",
            f"/v1/customers/{customer_id}/interactions",
            json={"channel": channel, "summary": summary},
            headers={"x-service-token": self.settings.crm_token},
        )

    # --- OfferMart -------------------------------------------------------
    async def offermart_products(self) -> list:
        return await self._call(
            "offermart",
            self.settings.offermart_base_url,
            "GET",
            "/v1/products",
            headers={"x-service-token": self.settings.offermart_token},
        )

    async def offermart_offer(self, customer_id: str) -> dict:
        return await self._call(
            "offermart",
            self.settings.offermart_base_url,
            "GET",
            f"/v1/offers/{customer_id}",
            headers={"x-service-token": self.settings.offermart_token},
        )

    async def offermart_evaluate(
        self, credit_score_band: str, monthly_income_paise: int, customer_id: str | None
    ) -> dict:
        return await self._call(
            "offermart",
            self.settings.offermart_base_url,
            "POST",
            "/v1/offers/evaluate",
            json={
                "credit_score_band": credit_score_band,
                "monthly_income_paise": monthly_income_paise,
                "customer_id": customer_id,
            },
            headers={"x-service-token": self.settings.offermart_token},
        )

    async def offermart_quote(
        self, principal_paise: int, tenure_months: int, product_code: str | None
    ) -> dict:
        return await self._call(
            "offermart",
            self.settings.offermart_base_url,
            "POST",
            "/v1/price",
            json={
                "principal_paise": principal_paise,
                "tenure_months": tenure_months,
                "product_code": product_code,
            },
            headers={"x-service-token": self.settings.offermart_token},
        )

    # --- lending core ----------------------------------------------------
    async def core_summary(self, customer_id: str) -> dict:
        token = await self._core_service_token()
        return await self._call(
            "core",
            self.settings.core_base_url,
            "GET",
            f"/internal/customers/{customer_id}/summary",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def core_eligibility(self, customer_id: str, amount_rupees: int, tenure_months: int) -> dict:
        token = await self._core_service_token()
        return await self._call(
            "core",
            self.settings.core_base_url,
            "POST",
            "/internal/eligibility/preview",
            json={
                "customer_id": customer_id,
                "amount_rupees": amount_rupees,
                "tenure_months": tenure_months,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    async def core_document(self, document_id: str) -> dict:
        token = await self._core_service_token()
        return await self._call(
            "core",
            self.settings.core_base_url,
            "GET",
            f"/internal/documents/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
        )


upstreams = Upstreams()
