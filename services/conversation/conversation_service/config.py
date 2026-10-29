"""Settings for the conversation service."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    env: str = "development"
    log_level: str = "INFO"
    service_name: str = "conversation-service"

    # --- state -----------------------------------------------------------
    database_url: str = "sqlite:///./data/conversation.db"

    # --- auth (shared HS256 secret with the core service) ----------------
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "core-service"
    jwt_audience: str = "tatabot-api"

    # --- core service ----------------------------------------------------
    core_base_url: str = "http://localhost:8000"
    core_timeout_seconds: float = 5.0
    core_max_retries: int = 2
    core_client_id: str = "conversation-service"
    core_client_secret: str = Field(min_length=16)

    # --- llm -------------------------------------------------------------
    llm_enabled: bool = False
    google_api_key: str | None = None
    llm_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 8.0
    llm_max_output_tokens: int = 160
    max_llm_calls_per_session: int = 12

    # --- agent service (LangGraph orchestrator) --------------------------
    # When enabled, question-shaped messages are delegated to the agent graph instead of
    # being treated as an application step. The deterministic flow is untouched.
    agents_enabled: bool = True
    agents_base_url: str = "http://localhost:8004"
    agents_service_token: str = "agent-service-token-change-me"  # noqa: S105 - dev default
    agents_timeout_seconds: float = 20.0

    # --- http ------------------------------------------------------------
    allowed_origins: str = "http://localhost:8080"
    rate_limit_per_minute: int = 120
    max_message_chars: int = 1000

    @property
    def allowed_origins_list(self) -> list[str]:
        return [part.strip() for part in self.allowed_origins.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
