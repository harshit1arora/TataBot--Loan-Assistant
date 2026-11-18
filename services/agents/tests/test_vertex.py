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

def test_gemini_role_keys_and_router_only_mode():
    import pytest
    from agents.config import ROLES, validate_role_keys

    keys = {f"gemini_api_key_{role}": f"test-{role}" for role in ROLES}
    configured = replace(settings, llm_provider="gemini", vertex_enabled=False,
                         require_role_keys=True, **keys)
    validate_role_keys(configured)
    with patch("google.genai.Client") as client:
        for role in ROLES:
            assert build_llm(configured, role).available
            client.assert_called_with(api_key=f"test-{role}")
        client.reset_mock()
        assert not build_llm(replace(configured, model_worker_replies=False), "faq").available
        client.assert_not_called()
    with pytest.raises(ValueError, match="five distinct"):
        validate_role_keys(replace(configured, gemini_api_key_interest="test-router"))
    with pytest.raises(ValueError, match="five distinct"):
        validate_role_keys(replace(configured, gemini_api_key_document=""))
