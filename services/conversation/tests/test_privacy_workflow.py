from datetime import UTC, datetime, timedelta
from conftest import fresh_customer, make_salary_pdf
from sqlalchemy import select
from core_service.db import SessionLocal as CoreDB
from core_service.models import Customer, Document, PrivacyRequest
from core_service.services import privacy
from conversation_service.db import SessionLocal as ChatDB
from conversation_service.models import ConversationSession, Message


def test_withdraw_retry_and_erasure(client, core_client, monkeypatch):
    cid, auth = fresh_customer(core_client)
    chat = client.post("/chat", json={"message": "hello"}, headers=auth)
    assert chat.status_code == 200, chat.text
    sid = chat.json()["session_id"]
    app = core_client.post("/v1/applications", headers=auth, json={"requested_amount_rupees": 100000, "tenure_months": 24})
    assert app.status_code == 201, app.text
    doc = core_client.post("/v1/documents", headers=auth, data={"doc_type": "salary_slip", "application_id": app.json()["application_id"]}, files={"file": ("salary.pdf", make_salary_pdf(), "application/pdf")})
    assert doc.status_code == 201, doc.text
    doc_id = doc.json()["document_id"]
    signed = core_client.get(f"/v1/documents/{doc_id}/signed-url", headers=auth).json()["url"]
    with CoreDB() as db:
        from core_service.storage import build_store
        from core_service.config import get_settings
        store = build_store(get_settings())
        key = db.get(Document, doc_id).storage_key
    assert store.exists(key)
    assert core_client.post("/v1/privacy/withdraw", headers=auth).json()["status"] == "withdrawn"
    assert core_client.get("/v1/customers/me", headers=auth).status_code == 403
    assert core_client.get(signed).status_code == 404
    assert client.post("/chat", json={"message": "hello"}, headers=auth).status_code == 403
    assert core_client.post("/v1/privacy/erase", headers=auth, json={"confirm": "ERASE"}).status_code == 202
    monkeypatch.setattr(privacy, "_conversation", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    assert privacy.process_pending() == 0
    with CoreDB() as db:
        assert db.get(PrivacyRequest, cid).status == "erasure_pending"
        assert db.get(Customer, cid) is not None
    def call(path, body):
        result = client.post("/internal/privacy/" + path, json=body, headers={"X-Privacy-Secret": "test-service-secret"})
        assert result.status_code == 200, result.text
    monkeypatch.setattr(privacy, "_conversation", call)
    assert privacy.process_pending() == 1
    assert core_client.get("/v1/privacy", headers=auth).json()["status"] == "local_erased"
    assert not store.exists(key)
    with CoreDB() as db:
        assert db.get(Customer, cid) is None
        assert db.get(Document, doc_id) is None
    with ChatDB() as db:
        assert db.get(ConversationSession, sid) is None
        assert not list(db.scalars(select(Message).where(Message.session_id == sid)))
    assert privacy.process_pending() == 0


def test_retention_requires_secret_and_deletes_only_old_sessions(client, core_client):
    cid, auth = fresh_customer(core_client)
    first = client.post("/chat", json={"message": "hello"}, headers=auth).json()["session_id"]
    second = client.post("/chat", json={"message": "hello"}, headers=auth).json()["session_id"]
    with ChatDB() as db:
        db.get(ConversationSession, first).updated_at = datetime.now(UTC) - timedelta(days=40)
        db.commit()
    assert client.post("/internal/privacy/retention", json={"days": 30}).status_code == 401
    r = client.post("/internal/privacy/retention", json={"days": 30}, headers={"X-Privacy-Secret": "test-service-secret"})
    assert r.status_code == 200, r.text
    with ChatDB() as db:
        assert db.get(ConversationSession, first) is None
        assert db.get(ConversationSession, second) is not None
