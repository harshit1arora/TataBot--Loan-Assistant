"""Vercel entrypoint for the conversation service."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "services" / "conversation"))
sys.path.insert(0, str(_ROOT / "api"))

from _shim import StripPrefix  # noqa: E402
from conversation_service.main import app as conversation_app  # noqa: E402

app = StripPrefix(conversation_app, "/api/conversation")
