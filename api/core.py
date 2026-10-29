"""Vercel entrypoint for the core lending service.

The service package is imported from services/core so the deployed function runs exactly
the same code the tests exercise — no copy, no separate build.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "services" / "core"))
sys.path.insert(0, str(_ROOT / "api"))

from _shim import StripPrefix  # noqa: E402
from core_service.main import app as core_app  # noqa: E402

# Vercel serves the module-level ASGI app.
app = StripPrefix(core_app, "/api/core")
