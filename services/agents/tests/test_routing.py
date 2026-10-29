"""Routing: does the orchestrator send a question to the right workers?"""
from __future__ import annotations

import pytest
from agents.graph import AgentGraph
from agents.router import WORKERS, rule_route, validate_route
from conftest import FakeLLM


@pytest.mark.parametrize(
    "question,expected_first",
    [
        ("would I get a 5 lakh loan?", "eligibility"),
        ("am I eligible for 300000", "eligibility"),
        ("what is the emi on 3 lakh for 24 months", "interest"),
        ("how much interest would I pay over 36 months", "interest"),
        ("which documents do I need to upload", "document"),
        ("my salary slip was rejected", "document"),
        ("is my data shared with anyone", "faq"),
        ("how do I raise a grievance", "faq"),
    ],
)
def test_rule_router_picks_the_expected_worker(question, expected_first):
    workers, reason = rule_route(question, max_workers=2)
    assert workers[0] == expected_first, f"{question!r} routed to {workers} ({reason})"
    assert reason


def test_router_always_returns_something():
    workers, reason = rule_route("hello there", max_workers=2)
    assert workers == ["faq"]
    assert "defaulting" in reason


def test_multi_domain_question_fans_out_but_is_capped():
    workers, _ = rule_route("can I get 5 lakh and what emi would that be", max_workers=2)
    assert set(workers) == {"eligibility", "interest"}
    assert len(workers) == 2

    capped, _ = rule_route("eligibility emi documents privacy", max_workers=1)
    assert len(capped) == 1


def test_router_validation_rejects_invented_agents():
    with pytest.raises(ValueError):
        validate_route({"agents": ["credit_bureau"]}, max_workers=2)
    with pytest.raises(ValueError):
        validate_route({"agents": []}, max_workers=2)
    with pytest.raises(ValueError):
        validate_route({"agents": "eligibility"}, max_workers=2)


def test_router_validation_dedupes_and_caps():
    workers, reason = validate_route(
        {"agents": ["eligibility", "ELIGIBILITY", "interest", "faq"], "reason": "test"}, max_workers=2
    )
    assert workers == ["eligibility", "interest"]
    assert reason == "test"


async def test_graph_follows_an_llm_route(toolbox):
    """With a model available, the graph goes where the model says — validated."""
    llm = FakeLLM(route={"agents": ["interest"], "reason": "asks for an EMI"})
    graph = AgentGraph(toolbox.settings, llm, toolbox)

    result = await graph.run("tell me the monthly outflow for 2 lakh over 18 months", "CUST001")

    assert result["route"] == ["interest"]
    assert result["route_reason"] == "asks for an EMI"
    assert any("llm:groq" in step for step in result["steps"])
    assert "EMI" in result["answer"] or "emi" in result["answer"].lower()


async def test_an_invalid_llm_route_falls_back_to_rules(toolbox):
    """A model that invents a worker must not be obeyed."""
    llm = FakeLLM(route={"agents": ["bureau_pull"], "reason": "made up"})
    graph = AgentGraph(toolbox.settings, llm, toolbox)

    result = await graph.run("what is the emi on 3 lakh for 24 months", "CUST001")

    assert result["route"] == ["interest"]  # rules path
    assert any("rules" in step for step in result["steps"])


async def test_a_broken_model_falls_back_to_rules(toolbox):
    llm = FakeLLM(route=None)  # complete_json raises
    graph = AgentGraph(toolbox.settings, llm, toolbox)

    result = await graph.run("am I eligible for 200000", "CUST001")
    assert result["route"] == ["eligibility"]
    assert result["answer"]


def test_every_worker_has_a_scope_description():
    for name, scope in WORKERS.items():
        assert len(scope) > 20, f"{name} has no usable description for the router prompt"


async def test_topology_matches_the_compiled_graph(graph):
    topology = graph.topology()
    assert topology["entry"] == "router"
    assert set(topology["workers"]) == set(WORKERS)
    assert "synthesise" in topology["nodes"]
    assert len(topology["edges"]) == 1 + len(WORKERS) + 1
