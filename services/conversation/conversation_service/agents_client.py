"""Client for the agent service.

The conversation service keeps its deterministic application flow and delegates *questions*
to the LangGraph orchestrator. One token, one timeout, and a failure that degrades to a
template instead of a 500.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .config import Settings

logger = logging.getLogger("conversation.agents")


class AgentsUnavailable(RuntimeError):
    pass


class AgentsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._failures = 0
        self._opened_at: float | None = None

    def _circuit_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at > 30:
            self._failures = 0
            self._opened_at = None
            return False
        return True

    async def ask(
        self,
        question: str,
        customer_id: str | None,
        document_id: str | None = None,
    ) -> dict:
        if self._circuit_open():
            raise AgentsUnavailable("circuit open")

        payload: dict = {"question": question}
        if customer_id:
            payload["customer_id"] = customer_id
        if document_id:
            payload["document_id"] = document_id

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    base_url=self.settings.agents_base_url,
                    timeout=httpx.Timeout(self.settings.agents_timeout_seconds),
                ) as client:
                    response = await client.post(
                        "/agent/query",
                        json=payload,
                        headers={"x-service-token": self.settings.agents_service_token},
                    )
                if response.status_code >= 500:
                    raise AgentsUnavailable(f"agents returned {response.status_code}")
                if response.status_code >= 400:
                    raise AgentsUnavailable(f"agents refused: {response.status_code}")
                self._failures = 0
                return response.json()
            except (httpx.HTTPError, AgentsUnavailable) as exc:
                logger.warning("agent call failed (%s)", type(exc).__name__)
                if attempt == 0:
                    await asyncio.sleep(0.2)
                    continue
                self._failures += 1
                if self._failures >= 3:
                    self._opened_at = time.monotonic()
                raise AgentsUnavailable(str(exc)) from exc
        raise AgentsUnavailable("agent call failed")
