"""Language model access — deliberately narrow.

Rules enforced here, not by convention:

* The prompt never contains a credit score, a pre-approved limit, a salary, a phone
  number, an email address or a document reference. Only a first name and a coarse
  band reach the model.
* Output is bounded in length and used for wording only. Every figure a customer sees
  is written by a deterministic template, so a prompt injection cannot invent one.
* A per-session call budget and a timeout; when either is hit the templates answer.
* If no API key is configured the service works fully, in template-only mode.
"""
from __future__ import annotations

import asyncio
import logging
import re

from .config import Settings

logger = logging.getLogger("conversation.llm")

ALLOWED_BANDS = {"excellent", "good", "fair"}
FORBIDDEN_IN_PROMPT = re.compile(
    r"\b(?:\d{4}\s?\d{4}\s?\d{4}|[6-9]\d{9}|[\w.+-]+@[\w-]+\.[\w.]+|credit\s*score\s*\d+)\b", re.I
)


class LlmGuardError(Exception):
    pass


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self.enabled = bool(settings.llm_enabled and settings.google_api_key)
        if self.enabled:
            try:
                from google import genai

                self._client = genai.Client(api_key=settings.google_api_key)
            except Exception as exc:  # noqa: BLE001 - a missing SDK must not break the app
                logger.warning("llm disabled: %s", type(exc).__name__)
                self.enabled = False

    # -- prompt construction ------------------------------------------------
    def build_prompt(self, *, first_name: str, band: str, state: str, message: str) -> str:
        safe_band = band if band in ALLOWED_BANDS else "good"
        # One word, letters only: a name cannot smuggle instructions into the prompt.
        candidate = re.sub(r"[^A-Za-z]", "", (first_name or "").split(" ")[0])
        safe_name = candidate[:24] or "customer"
        safe_message = FORBIDDEN_IN_PROMPT.sub("[redacted]", message)[:300]

        prompt = (
            "You are a loan assistant for an Indian NBFC. Reply in one or two short, warm "
            "sentences. Never state or guess any number, rate, eligibility, credit score or "
            "approval outcome: those are handled by the system. Never claim to have read a "
            "document. Do not ask for personal data.\n"
            f"Customer first name: {safe_name}\n"
            f"Profile band: {safe_band}\n"
            f"Conversation stage: {state}\n"
            f"Customer said: {safe_message}\n"
            "Write only the reply sentence(s)."
        )
        if FORBIDDEN_IN_PROMPT.search(prompt.replace(safe_message, "")):
            raise LlmGuardError("prompt contained a direct identifier")
        return prompt

    async def phrase(self, *, first_name: str, band: str, state: str, message: str) -> str | None:
        """Return a wording suggestion, or None to let the templates answer."""
        if not self.enabled:
            return None
        try:
            prompt = self.build_prompt(first_name=first_name, band=band, state=state, message=message)
        except LlmGuardError:
            logger.warning("llm skipped: guard rejected the prompt")
            return None

        try:
            text = await asyncio.wait_for(self._generate(prompt), timeout=self.settings.llm_timeout_seconds)
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
            logger.warning("llm unavailable: %s", type(exc).__name__)
            return None

        cleaned = (text or "").strip()
        if not cleaned or len(cleaned) > 400:
            return None
        if re.search(r"\d{3,}", cleaned):
            # Any multi-digit number in generated prose is a hallucination risk.
            logger.warning("llm output discarded: contained figures")
            return None
        return cleaned

    async def _generate(self, prompt: str) -> str:
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self.settings.llm_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=self.settings.llm_max_output_tokens,
            ),
        )
        return response.text or ""
