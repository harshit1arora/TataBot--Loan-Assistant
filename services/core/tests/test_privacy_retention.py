from datetime import UTC, datetime, timedelta
from core_service.db import SessionLocal
from core_service.models import SupportAssignment, SupportMessage
from core_service.services.privacy import run_retention


def test_support_retention_uses_closure_date(monkeypatch):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        def add(id, status, closed_at):
            db.add(SupportMessage(id=id, reference=id, name="Test", contact="test@example.test", message="synthetic", status=status, created_at=now - timedelta(days=200), closed_at=closed_at))
        add("privacy_old", "closed", now - timedelta(days=100))
        add("privacy_recent", "closed", now - timedelta(days=1))
        add("privacy_legacy", "closed", None)
        add("privacy_open", "open", None)
        db.flush()
        db.add(SupportAssignment(message_id="privacy_old", owner="operator"))
        db.commit()
    monkeypatch.setenv("SUPPORT_RETENTION_DAYS", "90")
    monkeypatch.delenv("CONVERSATION_RETENTION_DAYS", raising=False)
    run_retention()
    with SessionLocal() as db:
        assert db.get(SupportMessage, "privacy_old") is None
        assert db.get(SupportAssignment, "privacy_old") is None
        assert all(db.get(SupportMessage, id) is not None for id in ("privacy_recent", "privacy_legacy", "privacy_open"))
