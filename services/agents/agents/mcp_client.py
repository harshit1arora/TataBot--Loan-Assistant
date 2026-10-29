"""MCP client used by every worker.

The workers never call an HTTP service directly — they call tools. That is the whole point
of putting the tool server in the middle: the agent's capability surface is the tool list,
not the network.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .config import Settings

logger = logging.getLogger("agents.mcp")


class ToolFailure(RuntimeError):
    """A tool call failed. Workers turn this into an explanation, never a crash."""

    def __init__(self, tool: str, detail: str) -> None:
        self.tool = tool
        self.detail = detail
        super().__init__(f"{tool}: {detail}")


class McpToolbox:
    """Thin async wrapper over a FastMCP client, with a per-call timeout."""

    def __init__(self, settings: Settings, client_factory=None) -> None:
        self.settings = settings
        self._client_factory = client_factory
        self.calls: list[str] = []  # trace of tools used, for the response

    def _make_client(self):
        if self._client_factory is not None:
            return self._client_factory()

        from fastmcp import Client

        if self.settings.mcp_transport == "inmemory":
            # Single-process mode: import the server object directly.
            import sys
            from pathlib import Path

            server_path = Path(__file__).resolve().parents[2] / "mcp-server"
            if str(server_path) not in sys.path:
                sys.path.insert(0, str(server_path))
            from mcp_server.server import mcp as server  # noqa: PLC0415

            return Client(server)
        return Client(self.settings.mcp_url)

    async def call(self, tool: str, **arguments: Any) -> Any:
        self.calls.append(tool)
        try:
            async with self._make_client() as client:
                result = await client.call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001 - any transport/tool error is data, not a crash
            detail = str(exc)
            logger.warning("tool %s failed: %s", tool, detail[:160])
            raise ToolFailure(tool, detail[:300]) from exc

        data = getattr(result, "data", None)
        if data is None:
            # Fall back to the text block if structured content was not provided.
            blocks = getattr(result, "content", []) or []
            text = " ".join(getattr(block, "text", "") for block in blocks).strip()
            try:
                return json.loads(text) if text else {}
            except json.JSONDecodeError:
                return {"text": text}
        return data

    async def available_tools(self) -> list[str]:
        async with self._make_client() as client:
            tools = await client.list_tools()
        return sorted(tool.name for tool in tools)
