import pytest
from conversation_service.db import SessionLocal
from conversation_service.models import ConversationSession
from sqlalchemy.orm.exc import StaleDataError


def test_identical_terms_after_restart_create_a_new_attempt(client, auth):
    def say(text, session=None):
        return client.post(
            "/chat", headers=auth, json={"message": text, "session_id": session}
        ).json()

    session = say("hello")["session_id"]
    first = say("I need 1 lakh for 24 months", session)
    say("start over", session)
    second = say("I need 1 lakh for 24 months", session)
    assert second["application"]["application_id"] != first["application"]["application_id"]
    trace = client.get(f"/sessions/{session}/trace", headers=auth).json()
    assert len({turn["trace_id"] for turn in trace["turns"]}) == 4


def test_stale_session_version_cannot_overwrite_a_newer_turn(client, auth):
    session_id = client.post("/chat", headers=auth, json={"message": "hello"}).json()["session_id"]
    with SessionLocal() as first, SessionLocal() as second:
        a = first.get(ConversationSession, session_id)
        b = second.get(ConversationSession, session_id)
        a.version += 1
        first.commit()
        b.version += 1
        with pytest.raises(StaleDataError):
            second.flush()
