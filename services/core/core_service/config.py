"""Typed application settings, loaded from environment / .env.

Every value that differs between environments is here; nothing security-relevant is
hardcoded. Required secrets have no default so the service refuses to boot without them.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- runtime ---------------------------------------------------------
    env: str = "development"
    log_level: str = "INFO"
    service_name: str = "core-service"

    # --- persistence -----------------------------------------------------
    # sqlite:///./data/core.db in development, postgresql+psycopg://... in production
    database_url: str = "sqlite:///./data/core.db"
    db_echo: bool = False

    # --- auth ------------------------------------------------------------
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    service_token_ttl_seconds: int = 300
    service_client_id: str = "conversation-service"
    service_client_secret: str = Field(min_length=16)
    # Demo login (customer_id + registered phone, no OTP). MUST be false in production.
    allow_demo_auth: bool = True
    signed_url_ttl_seconds: int = 60

    # --- http ------------------------------------------------------------
    # Comma-separated in the environment; parsed by the properties below.
    allowed_origins: str = "http://localhost:8080"
    rate_limit_per_minute: int = 120
    # Only read X-Forwarded-For when a proxy you control sets it. Otherwise a client
    # can spoof the header and dodge the per-IP rate limit.
    trust_proxy_headers: bool = False

    # --- storage / uploads ----------------------------------------------
    # "local" writes to storage_dir. "s3" is required on serverless platforms,
    # where the filesystem is ephemeral (Vercel, Lambda, Cloud Run).
    storage_backend: str = "local"
    storage_dir: str = "./data/storage"
    s3_bucket: str = ""
    s3_prefix: str = ""
    s3_region: str = "ap-south-1"
    s3_endpoint_url: str = ""
    max_upload_bytes: int = 5 * 1024 * 1024
    allowed_upload_types: str = "application/pdf,image/jpeg,image/png"
    # Extraction confidence below which a human must review the document.
    min_extraction_confidence: float = 0.75
    # OCR engine: auto | rapidocr | tesseract | disabled
    ocr_provider: str = "auto"
    # Minimum OCR engine confidence before its text is trusted at all.
    ocr_min_confidence: float = 0.55

    # --- credit policy ---------------------------------------------------
    policy_version: str = "2026.10-v1"
    min_credit_score: int = 700
    max_emi_to_income_ratio: float = 0.50
    pre_approved_multiple: float = 2.0
    min_loan_amount_rupees: int = 10_000
    max_loan_amount_rupees: int = 5_000_000
    min_tenure_months: int = 6
    max_tenure_months: int = 60
    default_tenure_months: int = 36
    annual_rate_percent: float = 12.0
    min_customer_age: int = 21
    max_customer_age: int = 60

    @property
    def allowed_origins_list(self) -> list[str]:
        return [part.strip() for part in self.allowed_origins.split(",") if part.strip()]

    @property
    def allowed_upload_types_list(self) -> list[str]:
        return [part.strip() for part in self.allowed_upload_types.split(",") if part.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    if settings.is_production and settings.allow_demo_auth:
        raise RuntimeError(
            "allow_demo_auth must be false when env=production: demo login bypasses OTP."
        )
    return settings
