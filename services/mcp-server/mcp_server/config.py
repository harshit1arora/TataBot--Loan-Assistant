"""Where the tool server finds its upstreams."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    core_base_url: str = os.environ.get("CORE_BASE_URL", "http://localhost:8000")
    crm_base_url: str = os.environ.get("CRM_BASE_URL", "http://localhost:8002")
    offermart_base_url: str = os.environ.get("OFFERMART_BASE_URL", "http://localhost:8003")
    core_client_id: str = os.environ.get("CORE_CLIENT_ID", "conversation-service")
    core_client_secret: str = os.environ.get("CORE_CLIENT_SECRET", "")
    crm_token: str = os.environ.get("MOCK_CRM_TOKEN", "mock-crm-token-change-me")
    offermart_token: str = os.environ.get("MOCK_OFFERMART_TOKEN", "mock-offermart-token-change-me")
    timeout_seconds: float = float(os.environ.get("TOOL_TIMEOUT_SECONDS", "5"))


settings = Settings()
