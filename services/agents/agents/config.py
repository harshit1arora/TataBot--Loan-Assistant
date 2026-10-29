"""Agent service settings."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    env: str = os.environ.get("ENV", "development")
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    # How the agent service reaches the MCP tool server.
    #   inmemory — import the server object (tests, single process)
    #   http     — connect to a running tool server (docker, production)
    mcp_transport: str = os.environ.get("MCP_TRANSPORT", "http")
    mcp_url: str = os.environ.get("MCP_URL", "http://localhost:8765/mcp")

    # LLM provider: "groq" | "gemini" | "rules". "rules" needs no key and is the default,
    # so the graph is fully functional (and testable) without a model.
    llm_provider: str = os.environ.get("LLM_PROVIDER", "rules")
    # One key per role, so a burst of eligibility questions cannot exhaust the quota the
    # router needs. A role without its own key falls back to GROQ_API_KEY.
    groq_api_key: str = os.environ.get("GROQ_API_KEY", "")
    groq_api_key_router: str = os.environ.get("GROQ_API_KEY_ROUTER", "")
    groq_api_key_eligibility: str = os.environ.get("GROQ_API_KEY_ELIGIBILITY", "")
    groq_api_key_interest: str = os.environ.get("GROQ_API_KEY_INTEREST", "")
    groq_api_key_document: str = os.environ.get("GROQ_API_KEY_DOCUMENT", "")
    groq_api_key_faq: str = os.environ.get("GROQ_API_KEY_FAQ", "")
    # Groq rotates its catalogue; llama-3.3-70b-versatile is not available on every
    # account any more. gpt-oss-20b is fast enough for routing and widely available.
    groq_model: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
    gemini_api_key: str = os.environ.get("GOOGLE_API_KEY", "")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    llm_timeout_seconds: float = float(os.environ.get("LLM_TIMEOUT_SECONDS", "12"))
    llm_max_output_tokens: int = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "500"))

    service_token: str = os.environ.get("AGENT_SERVICE_TOKEN", "agent-service-token-change-me")
    max_question_chars: int = int(os.environ.get("MAX_QUESTION_CHARS", "1000"))
    max_workers_per_turn: int = int(os.environ.get("MAX_WORKERS_PER_TURN", "2"))


ROLES: tuple[str, ...] = ("router", "eligibility", "interest", "document", "faq")


def _settings_factory() -> Settings:
    return Settings()


settings = Settings()


def key_for(role: str, settings: Settings | None = None) -> str:
    """The API key a role should use: its own, else the shared one, else empty."""
    active = settings or globals()["settings"]
    own = getattr(active, f"groq_api_key_{role}", "") or ""
    return own or active.groq_api_key


def key_report(settings: Settings | None = None) -> dict[str, str]:
    """Which roles have a key — never the key itself. Safe to log and to expose."""
    active = settings or globals()["settings"]
    report: dict[str, str] = {}
    for role in ROLES:
        if getattr(active, f"groq_api_key_{role}", ""):
            report[role] = "own"
        elif active.groq_api_key:
            report[role] = "shared"
        else:
            report[role] = "missing"
    return report
