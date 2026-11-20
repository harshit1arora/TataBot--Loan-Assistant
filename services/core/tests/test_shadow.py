"""Shadow scoring records real TreeSHAP outputs without influencing lending."""

import hashlib
import json
import math
from pathlib import Path

from core_service.db import SessionLocal
from core_service.main import app
from core_service.models import ShadowPrediction
from core_service.routers.identity import identity
from core_service.services import shadow
from sqlalchemy import select


def test_report_matches_shipped_model():
    report = json.loads(
        (Path(__file__).resolve().parents[3] / "docs" / "shadow-model-evaluation.json").read_text()
    )
    assert hashlib.sha256(shadow.MODEL_PATH.read_bytes()).hexdigest() == report["model_sha256"]
    assert set(report["group_metrics"]) == {
        "age_21_29",
        "age_30_44",
        "age_45_plus",
        "sex_1",
        "sex_2",
    }


def test_real_model_and_policy_isolation(client, auth_headers, monkeypatch):
    response = client.post(
        "/v1/applications",
        headers=auth_headers,
        json={"requested_amount_rupees": 100000, "tenure_months": 24},
    )
    assert response.status_code == 201, response.text
    decision = response.json()
    assert decision["status"] == "approved"
    with SessionLocal() as db:
        prediction = db.scalar(
            select(ShadowPrediction)
            .where(ShadowPrediction.application_id == decision["application_id"])
            .order_by(ShadowPrediction.created_at.desc())
        )
        assert prediction and prediction.status == "scored"
        assert 0 <= prediction.probability <= 1
        assert math.isclose(
            prediction.age_shap_log_odds + prediction.baseline_log_odds,
            prediction.raw_margin,
            abs_tol=1e-5,
        )
        assert prediction.policy_outcome == "approve"
        assert prediction.reason_codes and prediction.reason_codes[0].startswith("age_")
        assert prediction.disagreement == (
            prediction.probability >= prediction.comparison_threshold
        )
    monkeypatch.setenv("OIDC_REVIEWER_SUBJECTS", "test-reviewer")
    app.dependency_overrides[identity] = lambda: {"sub": "test-reviewer"}
    try:
        staff = client.get("/v1/operations/shadow")
        assert staff.status_code == 200 and any(
            x["application_id"] == decision["application_id"] for x in staff.json()
        )
        app.dependency_overrides[identity] = lambda: {"sub": "ordinary-user"}
        assert client.get("/v1/operations/shadow").status_code == 403
    finally:
        del app.dependency_overrides[identity]


def test_model_failure_cannot_change_policy(client, auth_headers, monkeypatch):
    def failure(age):
        raise RuntimeError("synthetic model failure")

    monkeypatch.setattr(shadow, "score", failure)
    response = client.post(
        "/v1/applications",
        headers=auth_headers,
        json={"requested_amount_rupees": 100000, "tenure_months": 24},
    )
    assert response.status_code == 201 and response.json()["status"] == "approved"
    with SessionLocal() as db:
        row = db.scalar(
            select(ShadowPrediction).where(
                ShadowPrediction.application_id == response.json()["application_id"]
            )
        )
        assert row and row.status == "unavailable" and row.error_type == "RuntimeError"


def test_shadow_storage_failure_does_not_abort_decision(client, auth_headers, monkeypatch):
    def fail_capture(*args):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(shadow, "capture", fail_capture)
    response = client.post(
        "/v1/applications",
        headers=auth_headers,
        json={"requested_amount_rupees": 100000, "tenure_months": 24},
    )
    assert response.status_code == 201 and response.json()["status"] == "approved"


def test_high_shadow_score_does_not_change_policy(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        shadow,
        "score",
        lambda age: {
            "model_sha256": "a" * 64,
            "probability": 0.99,
            "baseline_log_odds": 0.0,
            "age_shap_log_odds": 1.0,
            "raw_margin": 1.0,
            "comparison_threshold": 0.22,
            "reason_codes": ["age_increases_shadow_score"],
        },
    )
    response = client.post(
        "/v1/applications",
        headers=auth_headers,
        json={"requested_amount_rupees": 100000, "tenure_months": 24},
    )
    assert response.status_code == 201 and response.json()["status"] == "approved"
    with SessionLocal() as db:
        row = db.scalar(
            select(ShadowPrediction).where(
                ShadowPrediction.application_id == response.json()["application_id"]
            )
        )
        assert row and row.disagreement is True
