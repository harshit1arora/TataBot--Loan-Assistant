"""ASGI prefix stripping for the serverless entrypoints.

Vercel routes /api/core/* to api/core.py, so the function receives the rewritten path
(`/api/core/auth/token`) while the FastAPI app expects `/auth/token`. Stripping here
keeps the service code free of deployment-specific knowledge.
"""
from __future__ import annotations


from urllib.parse import parse_qsl, urlencode


class StripPrefix:
    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = prefix.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            params = parse_qsl(scope["query_string"].decode("ascii"), keep_blank_values=True)
            paths = [value for key, value in params if key == "__route"]
            if paths:
                scope = dict(scope)
                scope["path"] = paths[-1]
                scope["raw_path"] = scope["path"].encode()
                scope["query_string"] = urlencode([(k, v) for k, v in params if k != "__route"]).encode()
        if scope["type"] in ("http", "websocket") and scope["path"].startswith(self.prefix):
            scope = dict(scope)
            stripped = scope["path"][len(self.prefix) :]
            scope["path"] = stripped or "/"
            if scope.get("raw_path"):
                scope["raw_path"] = scope["path"].encode()
        await self.app(scope, receive, send)
