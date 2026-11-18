from dataclasses import replace
from unittest.mock import patch

from agents.config import settings
from agents.llm import build_llm


def test_vertex_uses_runtime_credentials_without_api_key():
    configured = replace(
        settings, llm_provider="gemini", vertex_enabled=True, vertex_project="demo-project",
        vertex_location="global", gemini_api_key="",
    )
    with patch("google.genai.Client") as constructor:
        model = build_llm(configured, "router")
    assert model.available
    assert model.name == "gemini"
    constructor.assert_called_once_with(vertexai=True, project="demo-project", location="global")
