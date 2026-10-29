"""Run the tool server.

    python -m mcp_server                 # stdio (what an MCP client spawns)
    python -m mcp_server --http --port 8765   # streamable HTTP for container use
"""
from __future__ import annotations

import argparse

from .server import mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="TataBot MCP tool server")
    parser.add_argument("--http", action="store_true", help="serve over streamable HTTP")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container bind
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
