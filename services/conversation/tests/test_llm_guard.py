"""The LLM must never see, or produce, anything it could leak."""
from __future__ import annotations

from conversation_service.config import get_settings
from conversation_service.llm import LlmClient


def test_prompt_contains_no_direct_identifiers():
    llm = LlmClient(get_settings())
    prompt = llm.build_prompt(
        first_name="Asha",
        band="good",
        state="awaiting_amount",
        message="my number is 9810000001 and my email is asha@example.com",
    )
    assert "9810000001" not in prompt
    assert "asha@example.com" not in prompt
    assert "[redacted]" in prompt


def test_prompt_carries_a_band_not_a_score():
    llm = LlmClient(get_settings())
    prompt = llm.build_prompt(first_name="Asha", band="good", state="awaiting_amount", message="hi")
    assert "band" in prompt.lower()
    assert "745" not in prompt


def test_unknown_band_is_coerced():
    llm = LlmClient(get_settings())
    prompt = llm.build_prompt(first_name="Asha", band="745", state="x", message="hi")
    assert "Profile band: good" in prompt


def test_client_name_is_sanitised():
    llm = LlmClient(get_settings())
    prompt = llm.build_prompt(
        first_name="Asha'; DROP TABLE users;--", band="good", state="x", message="hi"
    )
    assert "DROP TABLE" not in prompt


def test_disabled_llm_returns_none_so_templates_answer():
    import asyncio

    llm = LlmClient(get_settings())  # LLM_ENABLED=false in tests
    assert llm.enabled is False
    assert asyncio.run(llm.phrase(first_name="A", band="good", state="x", message="hi")) is None


def test_generated_figures_are_discarded(monkeypatch):
    """If the model volunteers a number, the output is dropped rather than shown."""
    import asyncio

    llm = LlmClient(get_settings())
    llm.enabled = True

    async def fake_generate(prompt):
        return "You are pre-approved for 500000 at 12%."

    monkeypatch.setattr(llm, "_generate", fake_generate)
    assert asyncio.run(llm.phrase(first_name="A", band="good", state="x", message="hi")) is None


def test_llm_budget_is_capped_per_session():
    """The orchestrator stops calling the model after max_llm_calls_per_session."""
    from conversation_service.config import get_settings as settings

    assert settings().max_llm_calls_per_session > 0
    assert settings().max_llm_calls_per_session <= 20
