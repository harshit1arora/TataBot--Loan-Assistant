#!/usr/bin/env python3
"""Measure the paths the README quotes numbers for.

    python scripts/benchmark.py            # deterministic paths only
    LLM_PROVIDER=groq GROQ_API_KEY_...=… python scripts/benchmark.py --llm

Everything runs in-process against the real services; nothing is stubbed except the LLM
when `--llm` is not passed. Numbers are wall-clock on the machine you run it on, so treat
them as an order of magnitude, not a service level objective.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bootstrap() -> None:
    tmp = tempfile.mkdtemp(prefix="bench-")
    os.environ.update(
        {
            "ENV": "test",
            "DATABASE_URL": f"sqlite:///{tmp}/core.db",
            "STORAGE_DIR": f"{tmp}/storage",
            "JWT_SECRET": "benchmark-secret-long-enough-1234567890",
            "SERVICE_CLIENT_SECRET": "benchmark-service-secret-1234",
            "CORE_CLIENT_SECRET": "benchmark-service-secret-1234",
            "AGENTS_ENABLED": "false",
            "ALLOW_DEMO_AUTH": "true",
            "ALLOWED_ORIGINS": "http://localhost:8080",
            "RATE_LIMIT_PER_MINUTE": "100000",
            "MOCK_CRM_TOKEN": "bench-crm",
            "MOCK_OFFERMART_TOKEN": "bench-offert",
            "MCP_TRANSPORT": "inmemory",
            "LLM_PROVIDER": os.environ.get("LLM_PROVIDER", "rules"),
            "OMP_NUM_THREADS": "1",
            "ORT_NUM_THREADS": "1",
        }
    )
    for name in ("core", "mock-crm", "mock-offermart", "mcp-server", "conversation", "agents"):
        sys.path.insert(0, str(ROOT / "services" / name))
    os.environ["_BENCH_TMP"] = tmp


def _percentile(samples: list[float], share: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * share))
    return ordered[index]


def report(label: str, samples: list[float], unit: str = "ms") -> None:
    # samples are seconds
    scale = {"ms": 1_000, "us": 1_000_000}[unit]
    print(
        f"  {label:34} median {statistics.median(samples) * scale:8.3f} {unit}"
        f"   p95 {_percentile(samples, 0.95) * scale:8.3f} {unit}"
        f"   n={len(samples)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="also time a real model turn")
    parser.add_argument("--iterations", type=int, default=50)
    args = parser.parse_args()

    _bootstrap()

    import core_service.main as core_main
    import httpx
    import mock_crm.main as crm_main
    import mock_offermart.main as offm_main
    from core_service.config import get_settings
    from core_service.db import Base, SessionLocal, engine
    from core_service.money import compute_emi_paise
    from core_service.policy import Applicant, build_policy, decide
    from core_service.services import customers
    from fastapi.testclient import TestClient
    from mcp_server.upstreams import upstreams

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        customers.seed(db)
        db.commit()

    upstreams.transports = {
        "core": httpx.ASGITransport(app=core_main.app),
        "crm": httpx.ASGITransport(app=crm_main.app),
        "offermart": httpx.ASGITransport(app=offm_main.app),
    }
    upstreams.settings.__dict__["core_client_secret"] = "benchmark-service-secret-1234"  # noqa: S105
    offm_main.crm_transport = httpx.ASGITransport(app=crm_main.app)

    print("deterministic paths")
    policy = build_policy(get_settings())
    applicant = Applicant(
        customer_id="CUST001",
        age=32,
        credit_score=745,
        pre_approved_limit_paise=30_000_000,
        verified_income_paise=None,
    )
    samples = []
    for _ in range(args.iterations * 20):
        started = time.perf_counter()
        decide(policy, applicant, 20_000_000, 36)
        samples.append(time.perf_counter() - started)
    report("credit decision (policy)", samples, "us")

    samples = []
    for _ in range(args.iterations * 20):
        started = time.perf_counter()
        compute_emi_paise(50_000_000, 12.0, 36)
        samples.append(time.perf_counter() - started)
    report("EMI (integer paise)", samples, "us")

    print("\nfull turns (in-process, includes the database write)")
    from conversation_service.clients import CoreClient

    # The conversation service reads DATABASE_URL when imported; give it its own file now
    # that the core service has already bound its engine.
    os.environ["DATABASE_URL"] = f"sqlite:///{os.environ['_BENCH_TMP']}/conversation.db"
    import conversation_service.main as conv_main

    core = TestClient(core_main.app)
    token = core.post(
        "/auth/token", json={"customer_id": "CUST001", "phone": "9810000001"}
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    with TestClient(conv_main.app) as chat:
        chat.app.state.orchestrator.core = CoreClient(
            conv_main.settings, transport=httpx.ASGITransport(app=core_main.app)
        )
        chat.app.state.orchestrator.agents = None  # template path only

        samples = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            session = chat.post("/chat", json={"message": "hello"}, headers=auth).json()["session_id"]
            chat.post(
                "/chat",
                json={"message": "I need 2 lakh for 24 months", "session_id": session},
                headers=auth,
            )
            samples.append(time.perf_counter() - started)
        report("chat: greet + apply + decide", samples)

    router_mode = "groq" if os.environ.get("LLM_PROVIDER") == "groq" else "rules"
    print(f"\nagent graph ({router_mode} router, in-process)")
    import asyncio

    from agents.config import ROLES
    from agents.config import settings as agent_settings
    from agents.graph import AgentGraph
    from agents.llm import build_llm
    from agents.mcp_client import McpToolbox

    llms = {role: build_llm(agent_settings, role) for role in ROLES}
    graph = AgentGraph(agent_settings, toolbox=McpToolbox(agent_settings), llms=llms)
    questions = [
        "can I get 5 lakh for 36 months?",
        "what is the emi on 3 lakh over 24 months?",
        "which documents do I need?",
    ]

    async def time_agent() -> None:
        samples = []
        for index in range(args.iterations):
            started = time.perf_counter()
            await graph.run(questions[index % len(questions)], "CUST001")
            samples.append(time.perf_counter() - started)
        report(f"agent turn ({router_mode})", samples)

    asyncio.run(time_agent())

    print("\nOCR (payslip image, first call loads the model)")
    from io import BytesIO

    from core_service.extractors import build_extractor
    from core_service.ocr import build_ocr
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1200, 520), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40) if hasattr(ImageFont, "load_default") else None
    draw.text((50, 50), "Payslip - March 2026", fill="black", font=font)
    draw.text((50, 200), "Net Pay: 85000", fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()

    provider = build_ocr(os.environ.get("OCR_PROVIDER", "auto"))
    if provider.available():
        extractor = build_extractor(ocr_provider=provider, min_ocr_confidence=0.3)
        started = time.perf_counter()
        extractor("image/png", payload, 0.4)
        cold = time.perf_counter() - started
        samples = []
        for _ in range(max(3, args.iterations // 10)):
            started = time.perf_counter()
            extractor("image/png", payload, 0.4)
            samples.append(time.perf_counter() - started)
        print(f"  {'OCR cold start':34} {cold * 1000:8.1f} ms   (engine load)")
        report(f"OCR warm ({provider.name})", samples)
    else:
        print("  OCR disabled on this machine — skipped")

    if args.llm and os.environ.get("LLM_PROVIDER") == "groq":
        print("\nmodel turn (real Groq call)")
        samples = []

        async def time_llm() -> None:
            for index in range(3):
                started = time.perf_counter()
                await graph.run(questions[index % len(questions)], "CUST001")
                samples.append(time.perf_counter() - started)

        asyncio.run(time_llm())
        report("agent turn (groq)", samples)

    return 0


if __name__ == "__main__":
    sys.exit(main())
