"""The agent service HTTP surface."""
from __future__ import annotations

from conftest import AGENT_TOKEN


def test_health_reports_the_llm_and_transport(client):
    body = client.get("/health").json()
    assert body["service"] == "agents"
    assert body["llm"] == "rules"
    assert body["mcp_transport"] == "inmemory"
    assert body["checks"]["workers"] == "4"


def test_readiness_lists_the_mcp_tools(client):
    body = client.get("/ready").json()
    assert body["status"] == "ok"
    assert body["checks"]["mcp_tools"].startswith("ok (11)")


def test_the_graph_topology_is_inspectable(client):
    body = client.get("/agent/graph").json()
    assert body["entry"] == "router"
    assert set(body["workers"]) == {"eligibility", "interest", "document", "faq"}
    assert any(edge["type"].startswith("conditional") for edge in body["edges"])


def test_query_requires_a_service_token(client):
    response = client.post("/agent/query", json={"question": "am I eligible for 2 lakh"})
    assert response.status_code == 401
    wrong = client.post(
        "/agent/query",
        json={"question": "am I eligible for 2 lakh"},
        headers={"x-service-token": "nope"},
    )
    assert wrong.status_code == 401


def test_query_returns_route_steps_and_citations(client):
    response = client.post(
        "/agent/query",
        json={"question": "what is the emi on 5 lakh for 36 months", "customer_id": "CUST001"},
        headers=AGENT_TOKEN,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["route"] == ["interest"]
    assert body["decided_by"] == "rules"
    assert body["citations"]
    assert any("router" in step for step in body["steps"])
    assert any("synthesise" in step for step in body["steps"])
    assert body["data"]["interest"]["quote"]["emi_paise"] == 1_660_715


def test_query_validates_input(client):
    assert (
        client.post("/agent/query", json={"question": ""}, headers=AGENT_TOKEN).status_code == 422
    )
    assert (
        client.post(
            "/agent/query",
            json={"question": "hi", "customer_id": "not-a-customer"},
            headers=AGENT_TOKEN,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/agent/query",
            json={"question": "hi", "customer_id": "CUST001", "extra": 1},
            headers=AGENT_TOKEN,
        ).status_code
        == 422
    )


def test_a_question_without_a_customer_still_answers_policy_questions(client):
    body = client.post(
        "/agent/query", json={"question": "how do I raise a grievance"}, headers=AGENT_TOKEN
    ).json()
    assert body["route"] == ["faq"]
    assert "grievance" in body["answer"].lower()


def test_unknown_customer_is_reported_as_needs_input(client):
    body = client.post(
        "/agent/query",
        json={"question": "am I eligible for 2 lakh", "customer_id": "CUST999"},
        headers=AGENT_TOKEN,
    ).json()
    # The tool fails with a 404; the worker explains rather than crashing.
    assert body["answer"]
    assert "couldn't reach" in body["answer"].lower() or "try again" in body["answer"].lower()


# --- one key per role -------------------------------------------------------
def test_each_role_can_have_its_own_key():
    from agents.config import ROLES, Settings, key_for, key_report
    from agents.llm import GroqLLM

    settings = Settings(
        groq_api_key="shared-key",
        groq_api_key_router="router-key",
        groq_api_key_eligibility="elig-key",
        groq_api_key_interest="interest-key",
        groq_api_key_document="doc-key",
        groq_api_key_faq="faq-key",
    )
    assert key_report(settings) == dict.fromkeys(ROLES, "own")

    clients = {role: GroqLLM(settings, role) for role in ROLES}
    keys = {client._api_key for client in clients.values()}
    assert len(keys) == 5, "each role must use a different key"
    assert key_for("router", settings) == "router-key"
    assert key_for("faq", settings) == "faq-key"


def test_a_role_without_a_key_falls_back_to_the_shared_one():
    from agents.config import Settings, key_for, key_report

    settings = Settings(groq_api_key="shared-key", groq_api_key_router="router-key")
    assert key_for("router", settings) == "router-key"
    assert key_for("interest", settings) == "shared-key"
    report = key_report(settings)
    assert report["router"] == "own"
    assert report["interest"] == "shared"


def test_no_keys_means_rules_not_a_crash():
    from agents.config import Settings, key_report
    from agents.llm import RuleBasedLLM, build_llm

    settings = Settings(llm_provider="groq")
    assert key_report(settings) == {
        "router": "missing",
        "eligibility": "missing",
        "interest": "missing",
        "document": "missing",
        "faq": "missing",
    }
    client = build_llm(settings, "router")
    assert isinstance(client, RuleBasedLLM)
    assert client.available is False


def test_the_key_never_appears_in_a_repr_or_the_health_payload(client):
    from agents.config import Settings
    from agents.llm import GroqLLM

    secret = "gsk_supersecretvalue_do_not_print"
    llm = GroqLLM(Settings(groq_api_key=secret, llm_provider="groq"), "router")
    assert secret not in repr(llm)

    body = client.get("/health").json()
    assert secret not in str(body)
    models = client.get("/agent/models").json()
    assert secret not in str(models)
    assert set(models["keys"]) == {"router", "eligibility", "interest", "document", "faq"}


def test_the_graph_gives_each_worker_its_own_client(toolbox):
    from agents.config import ROLES, Settings
    from agents.graph import AgentGraph
    from agents.llm import GroqLLM

    settings = Settings(llm_provider="groq", groq_api_key="shared")
    llms = {role: GroqLLM(settings, role) for role in ROLES}
    graph = AgentGraph(settings, toolbox=toolbox, llms=llms)

    assert graph.router.llm is llms["router"]
    for name, worker in graph.workers.items():
        assert worker.llm is llms[name], f"{name} did not get its own client"
    assert graph.llm_summary()["router"] == "groq"
