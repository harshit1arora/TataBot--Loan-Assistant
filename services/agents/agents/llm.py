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
from decimal import Decimal
from functools import wraps
from typing import Protocol

from opentelemetry.trace import StatusCode

from .config import ROLES, Settings, key_for
from .observability import tracer
from .telemetry import active_worker, router_event

logger = logging.getLogger("agents.llm")

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def model_attempt(model: str) -> dict:
    record = active_worker.get()
    if record is None:
        record = router_event.get()
    attempt = {"model": model, "input": None, "output": None}
    if record is not None:
        record.setdefault("model_calls", []).append(attempt)
    return attempt


def traced_generation(fn):
    @wraps(fn)
    async def wrapped(self, *args, **kwargs):
        model = self.settings.gemini_model if self.name == "gemini" else self.settings.groq_model
        attributes = {
            "langfuse.observation.type": "generation",
            "gen_ai.request.model": model,
            "gen_ai.provider.name": self.name,
            "tatabot.role": self.role,
        }
        with tracer.start_as_current_span(
            "model.generate",
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                output = await fn(self, *args, **kwargs)
            except Exception:
                span.set_attribute("tatabot.model.status", "failed")
                span.set_status(StatusCode.ERROR)
                raise
            span.set_attribute("tatabot.model.status", "ok")
            record = active_worker.get()
            if record is None:
                record = router_event.get()
            calls = record.get("model_calls", []) if record else []
            if calls:
                for source, target in (
                    ("input", "gen_ai.usage.input_tokens"),
                    ("output", "gen_ai.usage.output_tokens"),
                ):
                    if isinstance(calls[-1].get(source), int):
                        span.set_attribute(target, calls[-1][source])
            return output

    return wrapped


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

                self._client = AsyncGroq(api_key=self._api_key, max_retries=0)
            except Exception as exc:  # noqa: BLE001 - a missing SDK must not break the app
                logger.warning("groq unavailable: %s", type(exc).__name__)
                self.available = False

    @traced_generation
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
        attempt = model_attempt(self.settings.groq_model)
        response = await asyncio.wait_for(
            self._client.chat.completions.create(**kwargs),
            timeout=self.settings.llm_timeout_seconds,
        )
        if usage := getattr(response, "usage", None):
            attempt.update(input=usage.prompt_tokens, output=usage.completion_tokens)
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
        api_key = key_for(role, settings)
        self.available = bool(settings.vertex_project if settings.vertex_enabled else api_key)
        self._client = None
        if self.available:
            try:
                from google import genai

                if settings.vertex_enabled:
                    self._client = genai.Client(
                        vertexai=True,
                        project=settings.vertex_project,
                        location=settings.vertex_location,
                    )
                else:
                    self._client = genai.Client(api_key=api_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("gemini unavailable: %s", type(exc).__name__)
                self.available = False

    @traced_generation
    async def complete(self, prompt: str, *, system: str = "") -> str:
        if not self.available or self._client is None:
            raise LlmUnavailable("gemini is not configured")
        from google.genai import types

        attempt = model_attempt(self.settings.gemini_model)
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
        usage = getattr(response, "usage_metadata", None)
        if usage and usage.prompt_token_count is not None and usage.total_token_count is not None:
            attempt.update(
                input=usage.prompt_token_count,
                output=usage.total_token_count - usage.prompt_token_count,
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
    if role != "router" and not settings.model_worker_replies:
        return RuleBasedLLM()
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


def _allowed_numbers(value: object, field: str = "") -> set[Decimal]:
    if isinstance(value, dict):
        return set().union(*(_allowed_numbers(item, key) for key, item in value.items()))
    if isinstance(value, list):
        return set().union(*(_allowed_numbers(item, field) for item in value))
    numbers = {Decimal(raw) for raw in numbers_in(str(value))}
    if field.endswith("_paise"):
        numbers.update(number / 100 for number in tuple(numbers))
    return numbers


def prose_is_grounded(prose: str, tool_output: str) -> bool:
    """Accept equivalent numeric spellings and rupee equivalents of explicit paise fields."""
    if not prose or not prose.strip():
        return False
    allowed = _allowed_numbers(json.loads(tool_output))
    return all(Decimal(raw) in allowed for raw in numbers_in(prose))
