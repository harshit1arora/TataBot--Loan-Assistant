"""Delivery retries, deduplication and overdue review scheduling."""

from datetime import UTC, datetime, timedelta

from core_service.db import SessionLocal
from core_service.models import Delivery
from core_service.services import notifications
from sqlalchemy import select


def test_delivery_retries_without_losing_message(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.test")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    received = []

    class FakeSMTP:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send_message(self, message):
            FakeSMTP.calls += 1
            if FakeSMTP.calls == 1:
                raise OSError("temporary outage")
            received.append(message)

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    with SessionLocal.begin() as db:
        notifications.enqueue(
            db, "test:retry", "customer", "person@example.test", "Update", "Sign in."
        )
        notifications.enqueue(
            db, "test:retry", "customer", "person@example.test", "Update", "Sign in."
        )
    assert notifications.deliver_once()
    with SessionLocal.begin() as db:
        item = db.scalar(select(Delivery).where(Delivery.event_key == "test:retry"))
        assert item and item.status == "pending" and item.attempts == 1
        item.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    assert notifications.deliver_once()
    with SessionLocal() as db:
        rows = list(db.scalars(select(Delivery).where(Delivery.event_key == "test:retry")))
        assert len(rows) == 1 and rows[0].status == "sent" and rows[0].attempts == 2
    assert len(received) == 1


def test_delivery_over_real_smtp_socket(monkeypatch):
    import socketserver
    import threading

    received = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 test ESMTP\r\n")
            while line := self.rfile.readline():
                command = line.upper()
                if command.startswith((b"EHLO", b"HELO")):
                    self.wfile.write(b"250 localhost\r\n")
                elif command.startswith((b"MAIL FROM", b"RCPT TO")):
                    self.wfile.write(b"250 OK\r\n")
                elif command.startswith(b"DATA"):
                    self.wfile.write(b"354 continue\r\n")
                    body = []
                    while (data := self.rfile.readline()) != b".\r\n":
                        body.append(data)
                    received.append(b"".join(body))
                    self.wfile.write(b"250 accepted\r\n")
                elif command.startswith(b"QUIT"):
                    self.wfile.write(b"221 bye\r\n")
                    break
                else:
                    self.wfile.write(b"250 OK\r\n")

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("SMTP_PORT", str(server.server_address[1]))
        monkeypatch.setenv("SMTP_FROM", "noreply@example.test")
        monkeypatch.setenv("SMTP_STARTTLS", "false")
        with SessionLocal.begin() as db:
            notifications.enqueue(
                db, "test:socket", "customer", "person@example.test", "Update", "Sign in."
            )
        try:
            assert notifications.deliver_once()
            assert len(received) == 1 and b"Sign in." in received[0]
        finally:
            server.shutdown()
            thread.join()
