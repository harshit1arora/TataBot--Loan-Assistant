"""End-to-end conversation tests against the real core service (in-process)."""
from __future__ import annotations

from conftest import make_salary_pdf


def _chat(client, auth, message, session_id=None):
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    return client.post("/chat", json=payload, headers=auth)


def test_chat_requires_a_token(client):
    assert client.post("/chat", json={"message": "hi"}).status_code == 401


def test_client_cannot_supply_workflow_state(client, auth):
    """The old API accepted current_state and trusted it. Now it is a 422."""
    response = client.post(
        "/chat",
        json={"message": "hi", "current_state": "sanction"},
        headers=auth,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_happy_path_within_pre_approved_limit(client, auth):
    first = _chat(client, auth, "hello")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["state"] == "awaiting_amount"
    assert "pre-approved limit" in body["reply"].lower()

    second = _chat(client, auth, "I need 2 lakh for 36 months", body["session_id"])
    assert second.status_code == 200, second.text
    result = second.json()
    assert result["state"] == "sanctioned"
    assert result["application"]["decision"]["outcome"] == "approve"
    assert result["sanction_document_id"], "an approved application should get a letter"
    assert "EMI" in result["reply"]


def test_above_limit_flow_requires_and_accepts_a_document(client, auth):
    body = _chat(client, auth, "hello").json()
    session_id = body["session_id"]

    # 5,00,000 against a 3,00,000 pre-approved limit needs verified income.
    pending = _chat(client, auth, "I need 5 lakh for 36 months", session_id).json()
    assert pending["state"] == "awaiting_document"
    assert pending["application"]["decision"]["outcome"] == "require_document"
    assert "salary slip" in pending["reply"].lower()

    upload = client.post(
        f"/sessions/{session_id}/documents",
        files={"file": ("slip.pdf", make_salary_pdf(85000), "application/pdf")},
        data={"doc_type": "salary_slip"},
        headers=auth,
    )
    assert upload.status_code == 200, upload.text
    result = upload.json()
    assert result["state"] == "sanctioned"
    assert result["application"]["decision"]["reason_codes"] == ["emi_within_foir"]
    assert result["sanction_document_id"]


def test_upload_outside_the_document_step_is_refused(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    response = client.post(
        f"/sessions/{session_id}/documents",
        files={"file": ("slip.pdf", make_salary_pdf(), "application/pdf")},
        headers=auth,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_rejected_application_is_explained(client, core_client):
    from conftest import _token

    # CUST004 has a credit score of 690.
    auth = {"Authorization": f"Bearer {_token(core_client, ('CUST004', '9810000004'))}"}
    session_id = _chat(client, auth, "hello").json()["session_id"]
    result = _chat(client, auth, "I need 1 lakh for 24 months", session_id).json()
    assert result["state"] == "rejected"
    assert "credit score" in result["reply"].lower()
    assert result["sanction_document_id"] is None


def test_restart_after_a_decision(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "I need 1 lakh for 24 months", session_id)
    restarted = _chat(client, auth, "new application", session_id).json()
    assert restarted["state"] == "awaiting_amount"


def test_session_belongs_to_one_customer(client, auth, other_auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    assert client.get(f"/sessions/{session_id}", headers=other_auth).status_code == 404
    assert client.get(f"/sessions/{session_id}/messages", headers=other_auth).status_code == 404

    # Nor can another customer continue the conversation.
    hijack = _chat(client, other_auth, "I need 1 lakh", session_id)
    assert hijack.status_code in (403, 404)


def test_status_and_transcript(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "I need 1 lakh for 24 months", session_id)

    status = client.get(f"/sessions/{session_id}", headers=auth).json()
    assert status["state"] == "sanctioned"
    assert status["application"]["status"] == "sanctioned"

    messages = client.get(f"/sessions/{session_id}/messages", headers=auth).json()
    roles = [m["role"] for m in messages]
    assert roles.count("customer") == 2
    assert roles.count("assistant") >= 2
    # No duplicated user turns: exactly one writer per message.
    assert roles[0] == "customer"


def test_malformed_message_is_rejected(client, auth):
    assert client.post("/chat", json={"message": ""}, headers=auth).status_code == 422
    assert client.post("/chat", json={"message": "x" * 5000}, headers=auth).status_code == 422


def test_rate_limit_applies_to_chat(client, auth, monkeypatch):
    from conversation_service.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 2, raising=False)
    statuses = [_chat(client, auth, "hello").status_code for _ in range(4)]
    assert 429 in statuses


def test_core_outage_degrades_gracefully(client, auth, monkeypatch):
    from conversation_service.clients import CoreServiceError

    async def boom(*args, **kwargs):
        raise CoreServiceError(503, "core_unavailable", "down")

    monkeypatch.setattr(client.app.state.orchestrator.core, "profile", boom)
    response = _chat(client, auth, "hello")
    assert response.status_code == 200
    assert "can't reach the lending service" in response.json()["reply"].lower()


def test_asking_for_a_human_returns_contact_options_without_moving_the_flow(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    result = _chat(client, auth, "can I talk to a human please?", session_id).json()

    assert result["intent"] == "contact"
    assert "1800-000-0000" in result["reply"]
    # A side channel must not advance or reset the workflow.
    assert result["state"] == "awaiting_amount"
    assert result["application"] is None


def test_support_words_are_not_mistaken_for_an_amount(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    result = _chat(client, auth, "I need to contact support about 50000", session_id).json()
    assert result["intent"] == "contact"
    assert result["state"] == "awaiting_amount", "no application should be created"


def test_support_works_after_a_decision_too(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    decided = _chat(client, auth, "I need 1 lakh for 24 months", session_id).json()
    assert decided["state"] == "sanctioned"

    result = _chat(client, auth, "grievance: I want to complain", session_id).json()
    assert result["intent"] == "contact"
    assert result["state"] == "sanctioned", "the decision is preserved"


def test_a_derived_limit_is_not_described_as_pre_approved(client, core_client):
    """A self-registered customer's limit is indicative, and the greeting says so."""
    from conftest import _token

    registration = core_client.post(
        "/v1/customers",
        json={
            "name": "Ishaan Kapoor",
            "phone": "9812345680",
            "email": "ishaan@example.com",
            "age": 34,
            "city": "Bhopal",
            "declared_monthly_income_rupees": 100000,
            "declared_credit_score": 750,
        },
    )
    assert registration.status_code == 201, registration.text
    customer_id = registration.json()["customer_id"]

    auth = {"Authorization": f"Bearer {_token(core_client, (customer_id, '9812345680'))}"}
    greeting = _chat(client, auth, "hello").json()

    assert "indicative limit" in greeting["reply"].lower()
    assert "pre-approved" not in greeting["reply"].lower()


# --- history ---------------------------------------------------------------
def test_a_customer_can_list_their_own_conversations(client, auth, other_auth):
    first = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "I need 2 lakh for 24 months", first)
    second = _chat(client, auth, "hello").json()["session_id"]

    listing = client.get("/sessions", headers=auth).json()
    ids = [row["session_id"] for row in listing["sessions"]]
    assert ids[0] == second, "newest conversation first"
    assert set(ids) >= {first, second}

    row = next(item for item in listing["sessions"] if item["session_id"] == first)
    assert row["message_count"] >= 4
    assert row["last_message"]
    assert row["state"] == "sanctioned"
    assert row["requested_amount_paise"] == 20_000_000

    # and not somebody else's
    others = client.get("/sessions", headers=other_auth).json()
    assert first not in [item["session_id"] for item in others["sessions"]]


def test_history_requires_a_token(client):
    assert client.get("/sessions").status_code == 401


def test_history_is_capped(client, auth):
    assert client.get("/sessions?limit=0", headers=auth).status_code == 422
    assert client.get("/sessions?limit=500", headers=auth).status_code == 422


def test_a_returning_customer_can_reopen_an_old_transcript(client, auth):
    session_id = _chat(client, auth, "hello").json()["session_id"]
    _chat(client, auth, "what documents do I need?", session_id)

    transcript = client.get(f"/sessions/{session_id}/messages", headers=auth).json()
    assert len(transcript) >= 4
    assert all("created_at" in row for row in transcript), "timestamps are part of the transcript"
    # The auto-start message is stored too, so the transcript opens with the customer turn.
    assert transcript[0]["role"] == "customer"
    assert transcript[1]["role"] == "assistant"
    assert "help you apply" in transcript[1]["content"].lower()
