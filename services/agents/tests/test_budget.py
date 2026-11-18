import os
from uuid import uuid4

import pytest
from agents.budget import BudgetUnavailable, model_call

pytestmark = pytest.mark.anyio


async def test_global_budget_and_concurrency(monkeypatch):
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("set TEST_REDIS_URL for the shared Redis integration")
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setenv("MODEL_CALLS_PER_MINUTE", "2")
    monkeypatch.setenv("MODEL_MAX_CONCURRENT", "1")
    provider = "integration-" + uuid4().hex
    async with model_call(provider, 5):
        with pytest.raises(BudgetUnavailable):
            async with model_call(provider, 5):
                pytest.fail("a second simultaneous lease was admitted")
    async with model_call(provider, 5):
        pass
    with pytest.raises(BudgetUnavailable):
        async with model_call(provider, 5):
            pytest.fail("the third call exceeded the shared minute budget")


async def test_exhausted_budget_falls_back_before_calling_model(monkeypatch, toolbox):
    from agents.graph import AgentGraph
    from conftest import FakeLLM

    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("set TEST_REDIS_URL for the shared Redis integration")
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setenv("MODEL_CALLS_PER_MINUTE", "0")
    llm = FakeLLM(route={"agents": ["faq"], "reason": "test"}, prose="invented")
    result = await AgentGraph(toolbox.settings, llm, toolbox).run("What is the privacy policy?")
    assert result["router_detail"]["fallback"] == "budget_unavailable"
    assert result["results"]["faq"]["trace"]["fallback"] == "budget_unavailable"
    assert result["citations"] and not llm.prompts
