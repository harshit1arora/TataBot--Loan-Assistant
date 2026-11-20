"""Cloud SQL monitor evaluates configuration, backup freshness and operational access."""

from datetime import UTC, datetime, timedelta

import pytest
from core_service.db import SessionLocal
from core_service.main import app
from core_service.models import BackupMonitor, Delivery
from core_service.routers.identity import identity
from core_service.services import backup_monitor, notifications
from sqlalchemy import select


class Response:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        return None

    def json(self):
        return self.value


class CloudSQL:
    def __init__(self, pitr=True, status="SUCCESSFUL", age_hours=1):
        self.pitr = pitr
        self.status = status
        self.age_hours = age_hours

    def get(self, url, **kwargs):
        if url.endswith("/backupRuns"):
            return Response(
                {
                    "items": [
                        {
                            "type": "AUTOMATED",
                            "status": self.status,
                            "endTime": (
                                datetime.now(UTC) - timedelta(hours=self.age_hours)
                            ).isoformat(),
                        }
                    ]
                }
            )
        return Response(
            {
                "settings": {
                    "backupConfiguration": {
                        "enabled": True,
                        "pointInTimeRecoveryEnabled": self.pitr,
                        "startTime": "02:00",
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "provider,expected",
    [
        (CloudSQL(), "healthy"),
        (CloudSQL(pitr=False), "degraded"),
        (CloudSQL(status="FAILED"), "degraded"),
        (CloudSQL(age_hours=40), "degraded"),
    ],
)
def test_status(provider, expected):
    assert (
        backup_monitor.inspect_target("test-project:test-instance", provider)["status"] == expected
    )


def test_unavailable_is_unknown():
    class Unavailable:
        def get(self, *args, **kwargs):
            raise TimeoutError()

    assert (
        backup_monitor.inspect_target("test-project:test-instance", Unavailable())["status"]
        == "unknown"
    )
    assert backup_monitor.inspect_target("bad/path:test", Unavailable())["issues"] == [
        "invalid_target"
    ]


def test_worker_poll_alert_and_authorized_dashboard(client, monkeypatch):
    monkeypatch.setenv("CLOUD_SQL_MONITOR_TARGETS", "example-project:db1")
    monkeypatch.setenv("ESCALATION_EMAIL", "alerts@example.test")
    monkeypatch.setenv("SMTP_HOST", "test")
    monkeypatch.setenv("SMTP_FROM", "sender@example.test")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    delivered = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send_message(self, message):
            delivered.append(message)

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("OIDC_REVIEWER_SUBJECTS", "monitor-reviewer")
    monkeypatch.setattr(backup_monitor.google.auth, "default", lambda **kwargs: (object(), None))
    monkeypatch.setattr(
        backup_monitor, "AuthorizedSession", lambda credential: CloudSQL(pitr=False)
    )
    app.dependency_overrides[identity] = lambda: {"sub": "monitor-reviewer"}
    try:
        with SessionLocal.begin() as db:
            backup_monitor.poll(db)
            backup_monitor.poll(db)
            records = list(db.scalars(select(Delivery).where(Delivery.category == "backup")))
            assert len(records) == 1
        assert notifications.deliver_once()
        assert len(delivered) == 1 and delivered[0]["To"] == "alerts@example.test"
        response = client.get("/v1/operations")
        assert response.status_code == 200
        result = response.json()["backup_monitor"][0]
        assert result["status"] == "degraded" and "pitr_disabled" in result["issues"]
        with SessionLocal.begin() as db:
            db.get(BackupMonitor, "example-project:db1").checked_at = datetime.now(UTC) - timedelta(
                hours=1
            )
        assert client.get("/v1/operations").json()["backup_monitor"][0]["status"] == "unknown"
        app.dependency_overrides[identity] = lambda: {"sub": "not-staff"}
        assert client.get("/v1/operations").status_code == 403
    finally:
        del app.dependency_overrides[identity]
        with SessionLocal.begin() as db:
            for record in db.scalars(select(Delivery).where(Delivery.category == "backup")):
                db.delete(record)
