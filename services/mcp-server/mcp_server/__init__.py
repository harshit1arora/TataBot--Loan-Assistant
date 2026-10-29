"""TataBot tool server (FastMCP).

Exposes the lending system's capabilities as MCP tools so the agent layer can call them
over a protocol instead of hardcoding URLs. Every tool is a thin, typed wrapper over an
upstream service — no business logic lives here, which is what keeps the agent honest.
"""
