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
    # Role-specific credentials share any organization-wide quota.
    # A role without its own key falls back to GROQ_API_KEY in non-strict mode.
    groq_api_key: str = os.environ.get("GROQ_API_KEY", "")
    groq_api_key_router: str = os.environ.get("GROQ_API_KEY_ROUTER", "")
    groq_api_key_eligibility: str = os.environ.get("GROQ_API_KEY_ELIGIBILITY", "")
    groq_api_key_interest: str = os.environ.get("GROQ_API_KEY_INTEREST", "")
    groq_api_key_document: str = os.environ.get("GROQ_API_KEY_DOCUMENT", "")
    groq_api_key_faq: str = os.environ.get("GROQ_API_KEY_FAQ", "")
    # Groq rotates its catalogue; llama-3.3-70b-versatile is not available on every
    # account any more. gpt-oss-20b is fast enough for routing and widely available.
    groq_model: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
    vertex_enabled: bool = os.environ.get('GOOGLE_GENAI_USE_VERTEXAI', '').lower() == 'true'
    vertex_project: str = os.environ.get('GOOGLE_CLOUD_PROJECT', '')
    vertex_location: str = os.environ.get('GOOGLE_CLOUD_LOCATION', 'global')
    gemini_api_key: str = os.environ.get("GOOGLE_API_KEY", "")
    gemini_api_key_router: str = os.environ.get("GOOGLE_API_KEY_ROUTER", "")
    gemini_api_key_eligibility: str = os.environ.get("GOOGLE_API_KEY_ELIGIBILITY", "")
    gemini_api_key_interest: str = os.environ.get("GOOGLE_API_KEY_INTEREST", "")
    gemini_api_key_document: str = os.environ.get("GOOGLE_API_KEY_DOCUMENT", "")
    gemini_api_key_faq: str = os.environ.get("GOOGLE_API_KEY_FAQ", "")
    require_role_keys: bool = os.environ.get("REQUIRE_ROLE_KEYS", "").lower() == "true"
    model_worker_replies: bool = os.environ.get("MODEL_WORKER_REPLIES", "true").lower() == "true"
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    llm_timeout_seconds: float = float(os.environ.get("LLM_TIMEOUT_SECONDS", "12"))
    llm_max_output_tokens: int = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "500"))

    turn_deadline_seconds: float = max(1.0, float(os.getenv("AGENT_TURN_DEADLINE_SECONDS", "32")))
    service_token: str = os.environ.get("AGENT_SERVICE_TOKEN", "agent-service-token-change-me")
    max_question_chars: int = int(os.environ.get("MAX_QUESTION_CHARS", "1000"))
    max_workers_per_turn: int = max(1, min(4, int(os.environ.get("MAX_WORKERS_PER_TURN", "4"))))


ROLES: tuple[str, ...] = ("router", "eligibility", "interest", "document", "faq")


def _settings_factory() -> Settings:
    return Settings()


settings = Settings()


def _key_prefix(active: Settings) -> str:
    return "gemini_api_key" if active.llm_provider.lower() == "gemini" else "groq_api_key"


def validate_role_keys(active: Settings) -> None:
    if not active.require_role_keys:
        return
    if active.llm_provider.lower() not in {"groq", "gemini"} or (
        active.llm_provider.lower() == "gemini" and active.vertex_enabled
    ):
        raise ValueError("REQUIRE_ROLE_KEYS requires Groq or the Gemini Developer API")
    keys = [getattr(active, f"{_key_prefix(active)}_{role}").strip() for role in ROLES]
    if not all(keys) or len(set(keys)) != len(ROLES):
        raise ValueError("Configure five distinct role keys for the selected provider")


def key_for(role: str, settings: Settings | None = None) -> str:
    """The API key a role should use: its own, else the shared one, else empty."""
    active = settings or globals()["settings"]
    own = getattr(active, f"{_key_prefix(active)}_{role}", "") or ""
    return own or getattr(active, _key_prefix(active))


def key_report(settings: Settings | None = None) -> dict[str, str]:
    """Which roles have a key — never the key itself. Safe to log and to expose."""
    active = settings or globals()["settings"]
    report: dict[str, str] = {}
    for role in ROLES:
        if active.llm_provider.lower() == "gemini" and active.vertex_enabled:
            report[role] = "vertex"
        elif getattr(active, f"{_key_prefix(active)}_{role}", ""):
            report[role] = "own"
        elif getattr(active, _key_prefix(active)):
            report[role] = "shared"
        else:
            report[role] = "missing"
    return report
