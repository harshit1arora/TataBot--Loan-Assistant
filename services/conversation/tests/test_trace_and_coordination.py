"""End-to-end evidence of how the two services coordinate."""
from __future__ import annotations

from conftest import fresh_customer, make_salary_pdf


def _chat(client, auth, message, session_id=None):
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    return client.post("/chat", json=payload, headers=auth)


def test_the_full_flow_records_the_expected_route(client, core_client):
    """Every step, in order, attributed to the component that did the work."""
    # A new customer: 6 × 1,20,000 = 7,20,000 indicative limit, no documents on file.
    _, auth = fresh_customer(core_client)
    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "I need 9 lakh for 36 months", session_id)

    trace = client.get(f"/sessions/{session_id}/trace", headers=auth).json()
    route = [(step["from_state"], step["event"], step["to_state"]) for step in trace["steps"]]

    assert route == [
        ("new", "greeting", "awaiting_amount"),
        ("awaiting_amount", "outcome_document_required", "awaiting_document"),
    ]
    assert trace["steps"][0]["handled_by"].startswith("conversation-service")
    assert "core-service" in trace["steps"][1]["handled_by"]
    assert trace["state"] == "awaiting_document"
    assert trace["application_id"]


def test_the_document_path_adds_the_extraction_step(client, core_client):
    _, auth = fresh_customer(core_client)
    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "I need 9 lakh for 36 months", session_id)
    client.post(
        f"/sessions/{session_id}/documents",
        files={"file": ("slip.pdf", make_salary_pdf(85000), "application/pdf")},
        headers=auth,
    )

    trace = client.get(f"/sessions/{session_id}/trace", headers=auth).json()
    events = [step["event"] for step in trace["steps"]]
    assert events == [
        "greeting",
        "outcome_document_required",
        "document_received",
        "outcome_approved",
    ]
    assert trace["state"] == "sanctioned"
    # The extraction step is attributed to the core service, not the orchestrator.
    extraction = next(step for step in trace["steps"] if step["event"] == "document_received")
    assert extraction["handled_by"].startswith("core-service")


def test_a_side_channel_does_not_appear_as_a_transition(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "can I talk to a human?", session_id)

    trace = client.get(f"/sessions/{session_id}/trace", headers=auth).json()
    assert [step["event"] for step in trace["steps"]] == ["greeting"]
    assert trace["state"] == "awaiting_amount"
    assert trace["messages"] >= 4  # greeting + question + two replies


def test_saying_restart_mid_flow_is_not_a_server_error(client, auth):
    """Regression: this used to raise TransitionNotAllowed and surface as a 500."""
    session_id = _chat(client, auth, "hello").json()["session_id"]
    response = _chat(client, auth, "new application", session_id)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "awaiting_amount"
    assert "amount" in response.json()["reply"].lower()


def test_restart_is_allowed_after_a_decision(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "I need 1 lakh for 24 months", session_id)
    restarted = _chat(client, auth, "start over", session_id).json()
    assert restarted["state"] == "awaiting_amount"

    trace = client.get(f"/sessions/{session_id}/trace", headers=auth).json()
    assert trace["steps"][-1]["event"] == "restart"
    assert trace["application_id"] is None, "a restart clears the previous application"


def test_the_trace_belongs_to_one_customer(client, auth, other_auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    assert client.get(f"/sessions/{session_id}/trace", headers=other_auth).status_code == 404


def test_the_llm_touches_only_the_greeting(client, auth, monkeypatch):
    """How much of the flow the model is allowed to influence: one turn, wording only."""
    orchestrator = client.app.state.orchestrator
    orchestrator.llm.enabled = True
    calls: list[str] = []

    async def fake_phrase(*, first_name, band, state, message):
        calls.append(state)
        return "Happy to help."

    monkeypatch.setattr(orchestrator.llm, "phrase", fake_phrase)

    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "I need 1 lakh for 24 months", session_id)
    _chat(client, auth, "can I talk to a human?", session_id)

    assert len(calls) == 1, f"the model was consulted {len(calls)} times: {calls}"
    assert calls[0] == "awaiting_amount"  # the greeting turn, before any decision


def test_a_new_session_is_created_when_no_session_id_is_sent(client, auth):
    first = _chat(client, auth, "hello").json()
    second = _chat(client, auth, "hello").json()
    assert first["session_id"] != second["session_id"]
