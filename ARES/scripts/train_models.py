"""Train ARES ML models on SIMULATED training episodes.

  1. Anomaly detector  - Isolation Forest (deployed) fitted on NOMINAL minutes only.
  2. Risk forecaster   - HistGradientBoosting + isotonic calibration (deployed):
                         P(level >= 2 within 30 min | currently < 2).

Candidate models (LOF, One-Class SVM, autoencoder, logistic regression) are
compared in scripts/evaluate.py on held-out astronauts. Inner validation for
choosing the anomaly reference distribution uses train subjects 12-15 only.

    python scripts/train_models.py
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")   # before numpy/sklearn import (see ares/__init__.py)
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ares.data.generate import DATA_DIR, HORIZON_MIN  # noqa: E402
from ares.intelligence.features import ANOMALY_FEATURES, FEATURE_NAMES  # noqa: E402
from ares.intelligence.models import MODELS_DIR, AnomalyModel, RiskForecaster  # noqa: E402


def nominal_mask(df: pd.DataFrame) -> pd.Series:
    """Truly nominal minutes: before scenario onset (or normal scenario), no truth event, no sensor fault."""
    pre = (df["min_since_onset"] < 0) | (df["scenario"] == "normal")
    return pre & (df["truth"] == 0) & (df["faults"].fillna("") == "")


def forecaster_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows eligible for forecasting: currently below level 2, with a full horizon ahead."""
    end = df.groupby("episode")["t"].transform("max")
    return df[(df["truth"] < 2) & (df["t"] <= end - HORIZON_MIN)]


def main():
    t0 = time.time()
    tr = pd.read_parquet(DATA_DIR / "train.parquet")
    print(f"train rows {len(tr):,} | subjects {tr.astronaut_index.nunique()} | episodes {tr.episode.nunique()}")
    inner_val = tr.astronaut_index >= 12

    # ---------------- anomaly
    nom = tr[nominal_mask(tr)]
    fit = nom[~inner_val.loc[nom.index]]
    ref = nom[inner_val.loc[nom.index]]
    rng = np.random.default_rng(0)
    fit_s = fit.sample(min(len(fit), 60_000), random_state=0)
    am = AnomalyModel().fit(fit_s[ANOMALY_FEATURES].to_numpy(), ref[ANOMALY_FEATURES].to_numpy(), seed=0)
    am.meta = {"model": "IsolationForest(n_estimators=100)", "features": ANOMALY_FEATURES,
               "fit_rows": len(fit_s), "reference_rows": len(ref), "data": "SIMULATED nominal minutes",
               "score": "percentile of nominal reference scores (0-1)", "trained": time.strftime("%Y-%m-%d")}
    am.save()
    print(f"anomaly: fit {len(fit_s):,} nominal rows, reference {len(ref):,}")

    # ---------------- forecaster
    fr = forecaster_rows(tr)
    X, y = fr[FEATURE_NAMES].to_numpy(), fr["y_future"].to_numpy()
    print(f"forecaster rows {len(fr):,}, positive rate {y.mean():.3f}")
    rf = RiskForecaster().fit(X, y, seed=0, groups=fr["astronaut_index"].to_numpy())
    rf.meta = {"model": "HistGradientBoostingClassifier + isotonic calibration on subject-grouped out-of-fold scores",
               "target": f"truth level >= 2 within next {HORIZON_MIN} min, given current truth level < 2",
               "features": FEATURE_NAMES, "rows": int(len(fr)), "positive_rate": round(float(y.mean()), 4),
               "data": "SIMULATED episodes, 16 synthetic subjects", "trained": time.strftime("%Y-%m-%d"),
               "caveat": "Predictive score of the simulator's dynamics - NOT a medically validated probability."}
    rf.save()
    # feature ranges seen in training -> runtime out-of-distribution monitoring
    q = tr[FEATURE_NAMES].quantile([0.001, 0.999])
    ranges = {f: [round(float(q.loc[0.001, f]), 4), round(float(q.loc[0.999, f]), 4)] for f in FEATURE_NAMES}
    (MODELS_DIR / "feature_ranges.json").write_text(json.dumps(ranges))
    import hashlib
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(MODELS_DIR.glob("*.joblib"))}
    meta = {"anomaly": am.meta, "forecaster": rf.meta, "sha256": hashes, "seconds": round(time.time() - t0, 1)}
    (MODELS_DIR / "model_card.json").write_text(json.dumps(meta, indent=2))
    print(f"saved to {MODELS_DIR} in {time.time() - t0:.0f}s")
    _ = rng


if __name__ == "__main__":
    main()
