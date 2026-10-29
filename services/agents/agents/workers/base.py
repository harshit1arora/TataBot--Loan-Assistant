"""Shared worker plumbing: call tools, then phrase the result safely."""
from __future__ import annotations

import json
import logging

from ..llm import LLM, LlmUnavailable, prose_is_grounded
from ..mcp_client import McpToolbox, ToolFailure

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
            prose = await self.llm.complete(prompt, system=system)
        except (LlmUnavailable, Exception) as exc:  # noqa: BLE001 - never fail on the model
            logger.info("%s: model unavailable (%s)", self.name, type(exc).__name__)
            return fallback

        if not prose_is_grounded(prose, json.dumps(tool_output, default=str)):
            logger.warning("%s: discarded model prose with ungrounded figures", self.name)
            return fallback
        return prose.strip()

    async def safe_call(self, tool: str, **arguments) -> tuple[dict | None, str | None]:
        """Returns (data, error_message). Workers degrade instead of raising."""
        try:
            return await self.toolbox.call(tool, **arguments), None
        except ToolFailure as exc:
            return None, exc.detail
