"""LLM access for the router and the workers.

Three providers behind one interface:

* ``GroqLLM``   — Llama 3.3 70B via Groq, used when ``GROQ_API_KEY`` is set.
* ``GeminiLLM`` — Gemini, as an alternative.
* ``RuleBasedLLM`` — no model at all. Deterministic, and the default, so the graph runs
  and is testable with no key and no network.

The guard that matters: a worker's prose is only accepted if every number in it appears in
the tool output the worker was given. Otherwise the deterministic template answers. That
way an LLM cannot invent an EMI, a rate or a limit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Protocol

from .config import ROLES, Settings, key_for

logger = logging.getLogger("agents.llm")

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class LlmUnavailable(RuntimeError):
    pass


class LLM(Protocol):
    name: str
    available: bool

    async def complete(self, prompt: str, *, system: str = "") -> str: ...
    async def complete_json(self, prompt: str, *, system: str = "") -> dict: ...


class RuleBasedLLM:
    """No model: callers fall back to their own deterministic path."""

    name = "rules"
    available = False

    async def complete(self, prompt: str, *, system: str = "") -> str:
        raise LlmUnavailable("no model configured")

    async def complete_json(self, prompt: str, *, system: str = "") -> dict:
        raise LlmUnavailable("no model configured")


class GroqLLM:
    name = "groq"

    def __init__(self, settings: Settings, role: str = "shared") -> None:
        self.settings = settings
        self.role = role
        self._api_key = key_for(role, settings) if role in ROLES else settings.groq_api_key
        self.available = bool(self._api_key)
        self._client = None
        if self.available:
            try:
                from groq import AsyncGroq

                self._client = AsyncGroq(api_key=self._api_key)
            except Exception as exc:  # noqa: BLE001 - a missing SDK must not break the app
                logger.warning("groq unavailable: %s", type(exc).__name__)
                self.available = False

    async def _chat(self, prompt: str, system: str, json_mode: bool) -> str:
        if not self.available or self._client is None:
            raise LlmUnavailable("groq is not configured")
        kwargs: dict = {
            "model": self.settings.groq_model,
            "messages": [
                {"role": "system", "content": system or "You are a precise assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": self.settings.llm_max_output_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await asyncio.wait_for(
            self._client.chat.completions.create(**kwargs),
            timeout=self.settings.llm_timeout_seconds,
        )
        return response.choices[0].message.content or ""

    async def complete(self, prompt: str, *, system: str = "") -> str:
        return await self._chat(prompt, system, json_mode=False)

    async def complete_json(self, prompt: str, *, system: str = "") -> dict:
        raw = await self._chat(prompt, system, json_mode=True)
        return json.loads(raw)


class GeminiLLM:
    name = "gemini"

    def __init__(self, settings: Settings, role: str = "shared") -> None:
        self.settings = settings
        self.role = role
        self.available = bool(settings.gemini_api_key)
        self._client = None
        if self.available:
            try:
                from google import genai

                self._client = genai.Client(api_key=settings.gemini_api_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("gemini unavailable: %s", type(exc).__name__)
                self.available = False

    async def complete(self, prompt: str, *, system: str = "") -> str:
        if not self.available or self._client is None:
            raise LlmUnavailable("gemini is not configured")
        from google.genai import types

        response = await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=self.settings.gemini_model,
                contents=f"{system}\n\n{prompt}" if system else prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2, max_output_tokens=self.settings.llm_max_output_tokens
                ),
            ),
            timeout=self.settings.llm_timeout_seconds,
        )
        return response.text or ""

    async def complete_json(self, prompt: str, *, system: str = "") -> dict:
        raw = await self.complete(prompt + "\n\nRespond with JSON only.", system=system)
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise LlmUnavailable("model did not return JSON")
        return json.loads(match.group(0))


def build_llm(settings: Settings, role: str = "router") -> LLM:
    """One client per role, each with its own key where one is configured."""
    provider = (settings.llm_provider or "rules").lower()
    if provider == "groq":
        client = GroqLLM(settings, role)
        # No key for this role: behave exactly like the no-model path rather than
        # failing a call first.
        return client if client.available else RuleBasedLLM()
    if provider == "gemini":
        gemini = GeminiLLM(settings, role)
        return gemini if gemini.available else RuleBasedLLM()
    return RuleBasedLLM()


def numbers_in(text: str) -> set[str]:
    return {match.replace(",", "") for match in NUMBER.findall(text or "")}


def _allowed_numbers(tool_output: str) -> set[str]:
    """Numbers a model may legitimately quote.

    Tools report money in paise; prose quotes rupees. So a tool value of 50000000 also
    permits 500000, and 1660715 permits 16607.15. Nothing else is derived — the model
    cannot scale, round or invent its way to a different figure.
    """
    allowed: set[str] = set()
    for raw in numbers_in(tool_output):
        allowed.add(raw)
        try:
            value = float(raw)
        except ValueError:
            continue
        if value and value % 100 == 0:
            allowed.add(f"{value / 100:.2f}".rstrip("0").rstrip("."))
        allowed.add(f"{value / 100:.2f}")
    return allowed


def prose_is_grounded(prose: str, tool_output: str) -> bool:
    """Every figure in the prose must come from the tool output.

    A model may phrase things; it may not introduce a number. Empty prose fails too.
    """
    if not prose or not prose.strip():
        return False
    allowed = _allowed_numbers(tool_output)
    for raw in numbers_in(prose):
        if raw in allowed:
            continue
        # Tolerate trailing-zero forms of an allowed value ("16,607.15" vs "16607.15").
        try:
            if f"{float(raw):.2f}" in allowed:
                continue
        except ValueError:
            return False
        return False
    return True
