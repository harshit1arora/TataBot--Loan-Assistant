"""Run the company demo against six isolated loopback services and a signed test issuer."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import httpx

from issuer import fixture

ROOT = Path(__file__).resolve().parents[2]
UNITS = {
    "core": "core_service",
    "conversation": "conversation_service",
    "mock-crm": "mock_crm",
    "mock-offermart": "mock_offermart",
    "mcp-server": "mcp_server",
    "agents": "agents",
}


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False
            )
        else:
            process.terminate()
        process.wait(timeout=15)


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="tatabot-lab-") as directory, ExitStack() as cleanup:
        with ExitStack() as reservations:
            sockets = {name: reservations.enter_context(socket.socket()) for name in UNITS}
            for sock in sockets.values():
                sock.bind(("127.0.0.1", 0))
            ports = {name: sock.getsockname()[1] for name, sock in sockets.items()}
        urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
        secret = secrets.token_urlsafe(40)
        env = dict(
            os.environ,
            ENV="test",
            ALLOW_DEMO_AUTH="true",
            JWT_SECRET=secret,
            SERVICE_CLIENT_SECRET=secret,
            CORE_CLIENT_SECRET=secret,
            AGENT_SERVICE_TOKEN=secret,
            MOCK_CRM_TOKEN=secret,
            MOCK_OFFERMART_TOKEN=secret,
            STORAGE_BACKEND="local",
            STORAGE_DIR=str(Path(directory) / "storage"),
            CORE_BASE_URL=urls["core"],
            CORE_URL=urls["core"],
            CONVERSATION_URL=urls["conversation"],
            AGENTS_BASE_URL=urls["agents"],
            AGENTS_URL=urls["agents"],
            MCP_URL=urls["mcp-server"] + "/mcp",
            MCP_TRANSPORT="http",
            CRM_BASE_URL=urls["mock-crm"],
            OFFERMART_BASE_URL=urls["mock-offermart"],
            PYTHONUTF8="1",
            LLM_PROVIDER="rules",
            LLM_ENABLED="false",
            REQUIRE_ROLE_KEYS="false",
            AGENTS_ENABLED="true",
            MAX_WORKERS_PER_TURN="4",
            REDIS_URL=os.getenv("TEST_REDIS_URL", ""),
        )
        if "--vertex" in sys.argv:
            env.update(
                LLM_PROVIDER="gemini", GOOGLE_GENAI_USE_VERTEXAI="true", REQUIRE_LIVE_GEMINI="1"
            )
            if not env.get("GOOGLE_CLOUD_PROJECT"):
                raise ValueError("Set GOOGLE_CLOUD_PROJECT for the live Vertex run")
        issuer = fixture(directory, env)
        cleanup.callback(issuer.server_close)
        cleanup.callback(issuer.shutdown)
        processes = []
        for name, module in UNITS.items():
            port = str(ports[name])
            args = (
                [module, "--http", "--host", "127.0.0.1", "--port", port]
                if name == "mcp-server"
                else ["uvicorn", module + ".main:app", "--host", "127.0.0.1", "--port", port]
            )
            log = cleanup.enter_context(open(Path(directory) / (name + ".log"), "wb"))
            process = subprocess.Popen(
                [sys.executable, "-m", *args],
                cwd=ROOT / "services" / name,
                env=dict(
                    env,
                    DATABASE_URL=(
                        f"postgresql+psycopg:///pilot_{name}"
                        if "--postgres" in sys.argv and name in ("core", "conversation")
                        else f"sqlite:///{directory}/{name}.db"
                    ),
                ),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            processes.append(process)
            cleanup.callback(stop, process)
        with httpx.Client(timeout=5) as client:
            until = time.monotonic() + 180
            while time.monotonic() < until:
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("A demo service failed to start.")
                try:
                    if client.get(urls["conversation"] + "/ready").is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise TimeoutError("Demo services did not become ready.")
        for script in ("company_demo.py", "agent_quality.py", "smoke_test.py"):
            subprocess.run([sys.executable, str(ROOT / "scripts" / script)], env=env, check=True)

        if "--browser" in sys.argv:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env["LAB_BROWSER_ORIGIN"] = f"http://127.0.0.1:{port}"
            web = subprocess.Popen(
                [
                    "node",
                    "node_modules/vite/bin/vite.js",
                    "--host",
                    "127.0.0.1",
                    "--strictPort",
                    "--port",
                    str(port),
                ],
                cwd=ROOT / "apps" / "web",
                env=dict(
                    env,
                    VITE_OIDC_ISSUER=env["OIDC_ISSUER"],
                    VITE_OIDC_CLIENT_ID=env["OIDC_AUDIENCE"],
                    VITE_CORE_URL=urls["core"],
                    VITE_CONVERSATION_URL=urls["conversation"],
                ),
            )
            cleanup.callback(stop, web)
            url = f"http://127.0.0.1:{port}"
            for _ in range(60):
                try:
                    if httpx.get(url).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "browser_demo.py"), url, "--local"],
                env=env,
                check=True,
            )
        for process in processes:
            stop(process)
        subprocess.run(
            [
                sys.executable,
                str(
                    ROOT
                    / "scripts"
                    / ("postgres_drill.py" if "--postgres" in sys.argv else "recovery_drill.py")
                ),
                directory,
            ],
            env=env,
            check=True,
        )


if __name__ == "__main__":
    run()
