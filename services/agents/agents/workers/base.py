"""Shared worker plumbing: call tools, then phrase the result safely."""

from __future__ import annotations

import json
import logging

from opentelemetry.trace import StatusCode

from ..budget import BudgetUnavailable, model_call
from ..llm import LLM, LlmUnavailable, prose_is_grounded
from ..mcp_client import McpToolbox, ToolFailure
from ..observability import tracer
from ..telemetry import active_worker

logger = logging.getLogger("agents.worker")


class Worker:
    name: str = "worker"
    description: str = ""

    def __init__(self, toolbox: McpToolbox, llm: LLM) -> None:
        self.toolbox = toolbox
        self.llm = llm

    async def run(self, state: dict) -> dict:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------
    async def phrase(
        self, *, instruction: str, tool_output: dict, fallback: str, system: str = ""
    ) -> str:
        """Let the model reword, but only if it invents no numbers."""
        if not self.llm.available:
            return fallback
        prompt = (
            f"{instruction}\n\n"
            "Use ONLY the facts in this JSON. Do not add any number that is not present.\n"
            f"JSON:\n{json.dumps(tool_output, indent=2, default=str)}\n\n"
            "Answer in at most three sentences, plain English, no markdown. "
            "Write rupee amounts with Indian digit grouping (₹5,00,000, not ₹500,000)."
        )
        try:
            async with model_call(self.llm.name, self.toolbox.settings.llm_timeout_seconds):
                prose = await self.llm.complete(prompt, system=system)
        except TimeoutError:
            if (record := active_worker.get()) is not None:
                record["fallback"] = "provider_timeout"
            return fallback
        except BudgetUnavailable:
            if (record := active_worker.get()) is not None:
                record["fallback"] = "budget_unavailable"
            return fallback
        except (LlmUnavailable, Exception) as exc:  # noqa: BLE001 - never fail on the model
            if (record := active_worker.get()) is not None:
                record["fallback"] = "model_unavailable"
            logger.info("%s: model unavailable (%s)", self.name, type(exc).__name__)
            return fallback

        if not prose_is_grounded(prose, json.dumps(tool_output, default=str)):
            if (record := active_worker.get()) is not None:
                record["fallback"] = "ungrounded_reply"
            logger.warning("%s: discarded model prose with ungrounded figures", self.name)
            return fallback
        if (record := active_worker.get()) is not None:
            record["wording"] = self.llm.name
            cfg = self.toolbox.settings
            record["model"] = cfg.gemini_model if self.llm.name == "gemini" else cfg.groq_model
        return prose.strip()

    async def safe_call(self, tool: str, **arguments) -> tuple[dict | None, str | None]:
        """Returns (data, error_message). Workers degrade instead of raising."""
        try:
            with tracer.start_as_current_span(
                "tool." + tool,
                attributes={"langfuse.observation.type": "tool", "gen_ai.tool.name": tool},
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    data = await self.toolbox.call(tool, **arguments)
                    span.set_attribute("tatabot.tool.status", "ok")
                except ToolFailure:
                    span.set_attribute("tatabot.tool.status", "failed")
                    span.set_status(StatusCode.ERROR)
                    raise
            if (record := active_worker.get()) is not None:
                record["tools"].append({"name": tool, "status": "ok"})
            return data, None
        except ToolFailure as exc:
            if (record := active_worker.get()) is not None:
                record["tools"].append({"name": tool, "status": "failed"})
            return None, exc.detail
