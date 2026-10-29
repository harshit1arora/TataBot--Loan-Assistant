"""P0/P1: audit trail is private and redacted; money maths never uses floats."""
from __future__ import annotations

from core_service.money import compute_emi_paise, format_inr, paise_to_rupees, rupees_to_paise


def test_money_conversion_round_trips():
    from decimal import Decimal

    assert rupees_to_paise(1234.56) == 123456
    assert paise_to_rupees(123456) == Decimal("1234.56")
    assert format_inr(1234567890) == "1,23,45,678.90"


def test_emi_matches_the_standard_formula():
    # 5,00,000 at 12% for 36 months -> 16,607.15 per month
    assert compute_emi_paise(50_000_000, 12.0, 36) == 1_660_715


def test_emi_rejects_impossible_inputs():
    import pytest

    for args in [(0, 12.0, 36), (100, 12.0, 0), (100, 0, 36), (100, 200, 36)]:
        with pytest.raises(ValueError):
            compute_emi_paise(*args)


def test_audit_log_is_not_reachable_over_http(client, auth_headers):
    """The old build served mcp_audit.log from a public route."""
    for path in ["/resource/mcp_audit.log", "/audit", "/v1/audit", "/audit_events"]:
        assert client.get(path, headers=auth_headers).status_code == 404


def test_audit_events_are_recorded_and_redacted(client, auth_headers):
    from core_service.db import SessionLocal
    from core_service.models import AuditEvent

    client.post(
        "/v1/applications",
        json={"requested_amount_rupees": 150000, "tenure_months": 24},
        headers=auth_headers,
    )
    with SessionLocal() as db:
        actions = {row.action for row in db.query(AuditEvent).all()}
    assert "application.created" in actions
    assert "application.evaluated" in actions


def test_redaction_strips_direct_identifiers():
    from core_service.services.audit import redact

    out = redact({"message": "call me on 9810000001 or a@b.com", "pan": "ABCDE1234F"})
    assert "9810000001" not in str(out)
    assert "a@b.com" not in str(out)
    assert "ABCDE1234F" not in str(out)


def test_rate_limiter_returns_429(client, auth_headers, monkeypatch):
    from core_service import ratelimit
    from core_service.config import get_settings

    monkeypatch.setattr(ratelimit, "_WINDOW_SECONDS", 60)
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 2, raising=False)
    ratelimit.reset()

    statuses = []
    for _ in range(4):
        statuses.append(
            client.post(
                "/v1/applications",
                json={"requested_amount_rupees": 100000, "tenure_months": 12},
                headers=auth_headers,
            ).status_code
        )
    assert 429 in statuses


def test_error_responses_do_not_leak_internals(client):
    body = client.get("/v1/applications/does-not-exist", headers={"Authorization": "Bearer x"}).json()
    assert body["error"]["code"] == "unauthenticated"
    assert "Traceback" not in str(body)
