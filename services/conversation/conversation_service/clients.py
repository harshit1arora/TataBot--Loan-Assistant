"""HTTP client for the core lending service.

Every call is async with an explicit timeout, bounded retries on transient failures, and
a circuit breaker so a sick dependency fails fast instead of piling up requests.
The customer's own access token is forwarded on customer-scoped calls: this service
never gains the ability to act for a customer who did not authenticate.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from .config import Settings


class CoreServiceError(Exception):
    """The core service refused or failed. Carries a safe code for the caller."""

    def __init__(self, status_code: int, code: str, message: str, details=None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"{code}: {message}")


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    _failures: int = 0
    _opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            self._failures = 0
            self._opened_at = None
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()


@dataclass
class _ServiceToken:
    value: str | None = None
    expires_at: float = 0.0


@dataclass
class CoreClient:
    settings: Settings
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    # Injecting a transport lets the tests drive the real core app in-process.
    transport: httpx.AsyncBaseTransport | None = None
    _service_token: _ServiceToken = field(default_factory=_ServiceToken)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.core_base_url,
            timeout=httpx.Timeout(self.settings.core_timeout_seconds),
            headers={"user-agent": "conversation-service/1.0"},
            transport=self.transport,
        )

    async def _request(
        self, method: str, path: str, *, customer_token: str | None = None, json: dict | None = None,
        data: dict | None = None, files: dict | None = None, idempotency_key: str | None = None,
    ) -> dict:
        if not self.breaker.allow():
            raise CoreServiceError(503, "core_unavailable", "The lending service is unavailable.")

        headers: dict[str, str] = {}
        if customer_token:
            headers["Authorization"] = f"Bearer {customer_token}"
        elif token := await self._get_service_token():
            headers["Authorization"] = f"Bearer {token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        last_error: Exception | None = None
        for attempt in range(self.settings.core_max_retries + 1):
            try:
                async with self._client() as client:
                    response = await client.request(
                        method, path, headers=headers, json=json, data=data, files=files
                    )
                if response.status_code >= 500:
                    last_error = CoreServiceError(502, "core_error", "The lending service failed.")
                    await asyncio.sleep(0.15 * (attempt + 1))
                    continue
                self.breaker.record_success()
                if response.status_code >= 400:
                    payload = response.json() if response.content else {}
                    error = payload.get("error", {})
                    raise CoreServiceError(
                        response.status_code,
                        error.get("code", "core_error"),
                        error.get("message", "Request rejected."),
                        error.get("details"),
                    )
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                await asyncio.sleep(0.15 * (attempt + 1))

        self.breaker.record_failure()
        raise CoreServiceError(503, "core_unavailable", "The lending service is unavailable.") from last_error

    async def _get_service_token(self) -> str | None:
        if self._service_token.value and time.monotonic() < self._service_token.expires_at - 5:
            return self._service_token.value
        try:
            async with self._client() as client:
                response = await client.post(
                    "/auth/service-token",
                    json={
                        "client_id": self.settings.core_client_id,
                        "client_secret": self.settings.core_client_secret,
                    },
                )
            if response.status_code != 200:
                return None
            body = response.json()
            self._service_token = _ServiceToken(
                value=body["access_token"], expires_at=time.monotonic() + body["expires_in"]
            )
            return self._service_token.value
        except httpx.HTTPError:
            return None

    # --- customer-scoped (token forwarded) -------------------------------
    async def profile(self, customer_token: str) -> dict:
        return await self._request("GET", "/v1/customers/me", customer_token=customer_token)

    async def create_application(
        self, customer_token: str, amount_rupees: int, tenure_months: int, idempotency_key: str
    ) -> dict:
        return await self._request(
            "POST",
            "/v1/applications",
            customer_token=customer_token,
            json={"requested_amount_rupees": amount_rupees, "tenure_months": tenure_months},
            idempotency_key=idempotency_key,
        )

    async def application(self, customer_token: str, application_id: str) -> dict:
        return await self._request(
            "GET", f"/v1/applications/{application_id}", customer_token=customer_token
        )

    async def issue_sanction(self, customer_token: str, application_id: str) -> dict:
        return await self._request(
            "POST", f"/v1/applications/{application_id}/sanction", customer_token=customer_token
        )

    async def upload_document(
        self,
        customer_token: str,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        doc_type: str,
        application_id: str | None,
    ) -> dict:
        data = {"doc_type": doc_type}
        if application_id:
            data["application_id"] = application_id
        return await self._request(
            "POST",
            "/v1/documents",
            customer_token=customer_token,
            data=data,
            files={"file": (filename, content, content_type)},
        )

    async def process_document(self, customer_token: str, document_id: str) -> dict:
        return await self._request("POST", f"/internal/documents/{document_id}/process")

    async def re_evaluate(self, customer_token: str, application_id: str) -> dict:
        return await self._request(
            "POST", f"/v1/applications/{application_id}/evaluate", customer_token=customer_token
        )

    async def document(self, customer_token: str, document_id: str) -> dict:
        return await self._request("GET", f"/v1/documents/{document_id}", customer_token=customer_token)

    async def signed_url(self, customer_token: str, document_id: str) -> dict:
        return await self._request(
            "GET", f"/v1/documents/{document_id}/signed-url", customer_token=customer_token
        )

    # --- service-scoped --------------------------------------------------
    async def internal_summary(self, customer_id: str) -> dict:
        return await self._request("GET", f"/internal/customers/{customer_id}/summary")
