"""Train an age-only shadow model and evaluate held-out age and sex groups."""

import argparse
import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "services/core/core_service/shadow_model.ubj"
REPORT = ROOT / "docs/shadow-model-evaluation.json"


def group_report(frame, probability, truth, mask, threshold):
    y, p = truth[mask], probability[mask]
    positives, negatives = int(y.sum()), int((1 - y).sum())
    predicted = p >= threshold
    return {
        "n": len(y),
        "defaults": positives,
        "non_defaults": negatives,
        "mean_score": float(p.mean()),
        "flag_rate": float(predicted.mean()),
        "true_positive_rate": float(predicted[y == 1].mean()) if positives else None,
        "false_positive_rate": float(predicted[y == 0].mean()) if negatives else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_zip", type=Path)
    args = parser.parse_args()
    raw = args.dataset_zip.read_bytes()
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".xls")]
        if len(names) != 1:
            raise ValueError("Expected one UCI workbook")
        df = pd.read_excel(BytesIO(archive.read(names[0])), header=1)
    df.columns = [str(col).strip() for col in df.columns]
    age, sex = df["AGE"].to_numpy(), df["SEX"].to_numpy()
    target = df["default payment next month"].to_numpy().astype(int)
    train, test = train_test_split(
        np.arange(len(df)), test_size=0.25, random_state=42, stratify=target
    )
    model = xgb.train(
        {
            "objective": "binary:logistic",
            "max_depth": 2,
            "eta": 0.05,
            "subsample": 1,
            "colsample_bytree": 1,
            "seed": 42,
            "nthread": 1,
        },
        xgb.DMatrix(age[train].reshape(-1, 1), label=target[train], feature_names=["age"]),
        num_boost_round=80,
    )
    x = xgb.DMatrix(age[test].reshape(-1, 1), feature_names=["age"])
    scores = model.predict(x)
    contributions = model.predict(x, pred_contribs=True)
    margins = model.predict(x, output_margin=True)
    assert np.allclose(contributions.sum(axis=1), margins, atol=1e-5)
    y = target[test]
    threshold = 0.22
    groups = {
        "age_21_29": age[test] < 30,
        "age_30_44": (age[test] >= 30) & (age[test] < 45),
        "age_45_plus": age[test] >= 45,
        "sex_1": sex[test] == 1,
        "sex_2": sex[test] == 2,
    }
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL)
    report = {
        "dataset": "UCI Default of Credit Card Clients",
        "dataset_url": "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients",
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
        "population": "Taiwan credit card clients, 2005",
        "license": "CC BY 4.0",
        "features": ["age"],
        "train_n": len(train),
        "test_n": len(test),
        "split_seed": 42,
        "risk_threshold_for_comparison": threshold,
        "positive_label": "next month credit card default",
        "roc_auc": float(roc_auc_score(y, scores)),
        "brier_score": float(brier_score_loss(y, scores)),
        "group_metrics": {
            name: group_report(df, scores, y, mask, threshold) for name, mask in groups.items()
        },
        "caveats": "Age-only demonstration on foreign historical credit-card data. Not an Indian personal-loan risk estimate. Sex is used for offline group evaluation only. Groups follow dataset codes; gender is not available in TataBot. Policy and model disagree is a simulation, not a validated fairness judgment.",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
