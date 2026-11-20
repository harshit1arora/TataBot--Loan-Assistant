"""Research-only challenger. The policy never reads its outputs."""

from __future__ import annotations

import hashlib
import math
import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Application, Customer, DecisionRecord, ShadowPrediction

MODEL_PATH = Path(__file__).resolve().parents[1] / "shadow_model.ubj"
THRESHOLD = 0.22


@lru_cache(maxsize=1)
def _model():
    import xgboost as xgb

    digest = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    model = xgb.Booster(params={"nthread": 1})
    model.load_model(str(MODEL_PATH))
    return model, digest


def score(age: int) -> dict:
    import numpy as np
    import xgboost as xgb

    model, digest = _model()
    matrix = xgb.DMatrix(np.array([[age]], dtype=np.float32), feature_names=["age"], nthread=1)
    probability = float(model.predict(matrix)[0])
    margin = float(model.predict(matrix, output_margin=True)[0])
    contributions = model.predict(matrix, pred_contribs=True)[0]
    age_effect, baseline = float(contributions[0]), float(contributions[1])
    if not all(math.isfinite(v) for v in (probability, margin, age_effect, baseline)):
        raise ValueError("Non-finite model output")
    if abs(age_effect + baseline - margin) > 1e-5:
        raise ValueError("Invalid SHAP decomposition")
    return {
        "model_sha256": digest,
        "probability": probability,
        "baseline_log_odds": baseline,
        "age_shap_log_odds": age_effect,
        "reason_codes": [
            "age_increases_shadow_score"
            if age_effect > 0
            else "age_decreases_shadow_score"
            if age_effect < 0
            else "age_neutral_shadow_score"
        ],
        "raw_margin": margin,
        "comparison_threshold": THRESHOLD,
    }


def capture(
    db: Session, application: Application, customer: Customer, decision: DecisionRecord
) -> None:
    values = {}
    status = "disabled"
    error_type = None
    if os.getenv("SHADOW_MODEL_ENABLED", "true").lower() == "true":
        try:
            values = score(customer.age)
            status = "scored"
        except Exception as exc:  # model failure cannot affect the lending decision
            status = "unavailable"
            error_type = type(exc).__name__
    disagreement = None
    if status == "scored" and decision.outcome in ("approve", "reject"):
        disagreement = (values["probability"] >= THRESHOLD) != (decision.outcome == "reject")
    db.add(
        ShadowPrediction(
            decision_id=decision.id,
            application_id=application.id,
            status=status,
            policy_outcome=decision.outcome,
            disagreement=disagreement,
            error_type=error_type,
            **values,
        )
    )
