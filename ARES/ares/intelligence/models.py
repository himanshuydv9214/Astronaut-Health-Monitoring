"""ML models: multivariate anomaly detection and short-horizon risk forecasting.

AnomalyModel
    Isolation Forest trained ONLY on nominal periods, in personal deviation
    space (ANOMALY_FEATURES). It answers "is this combination of deviations
    unusual for healthy operation?" - useful for patterns no rule anticipated.
    Raw scores are mapped to [0,1] by their percentile among held-out nominal
    samples, so 0.99 means "more unusual than 99% of nominal minutes".

RiskForecaster
    Gradient-boosted trees (sklearn HistGradientBoosting; same model family as
    XGBoost/LightGBM, no extra dependency) predicting P(level >= 2 within the
    next H minutes | currently level < 2). Isotonic calibration is fitted on
    subject-grouped out-of-fold scores.
    IMPORTANT: trained on SIMULATED episodes, so the output is a *predictive
    risk score of the simulator's dynamics*, not a medically validated
    probability. The UI labels it accordingly.

Explanations use SHAP TreeExplainer on the same booster (calibration is a monotone map).
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from ares.intelligence.features import ANOMALY_FEATURES, FEATURE_NAMES, to_vector

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


class AnomalyModel:
    def __init__(self, model=None, ref_scores=None, meta=None):
        self.model = model
        self.ref = np.sort(ref_scores) if ref_scores is not None else None
        self.meta = meta or {}

    @property
    def ready(self) -> bool:
        return self.model is not None

    def fit(self, X: np.ndarray, X_ref: np.ndarray, seed: int = 0, **kw) -> "AnomalyModel":
        from sklearn.ensemble import IsolationForest

        self.model = IsolationForest(n_estimators=100, contamination="auto", random_state=seed, **kw).fit(X)
        self.ref = np.sort(-self.model.score_samples(X_ref))
        return self

    def score(self, feats: dict) -> float | None:
        if not self.ready:
            return None
        raw = -self.model.score_samples(to_vector(feats, ANOMALY_FEATURES)[None, :])[0]
        return float(np.searchsorted(self.ref, raw) / len(self.ref))

    def save(self, path: Path = MODELS_DIR / "anomaly_iforest.joblib") -> None:
        joblib.dump({"model": self.model, "ref": self.ref, "meta": self.meta}, path)

    @classmethod
    def load(cls, path: Path = MODELS_DIR / "anomaly_iforest.joblib") -> "AnomalyModel":
        if not Path(path).exists():
            return cls()
        d = joblib.load(path)
        return cls(d["model"], d["ref"], d.get("meta"))


class RiskForecaster:
    def __init__(self, booster=None, calibrator=None, meta=None):
        self.booster = booster
        self.calibrator = calibrator
        self.meta = meta or {}
        self._explainer = None

    @property
    def ready(self) -> bool:
        return self.booster is not None and self.calibrator is not None

    PARAMS = dict(max_iter=250, learning_rate=0.06, max_leaf_nodes=31, l2_regularization=1.0,
                  class_weight="balanced", random_state=0)

    def fit(self, X: np.ndarray, y: np.ndarray, seed: int = 0, groups: np.ndarray | None = None) -> "RiskForecaster":
        """One booster; isotonic calibration fitted on OUT-OF-FOLD scores (group k-fold by
        subject when groups are given, so calibration never sees a subject's own training rows).
        SHAP explanations therefore describe exactly the model that makes the prediction."""
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.isotonic import IsotonicRegression
        from sklearn.model_selection import GroupKFold, KFold, cross_val_predict

        params = dict(self.PARAMS, random_state=seed)
        cv = GroupKFold(3) if groups is not None else KFold(3, shuffle=True, random_state=seed)
        oof = cross_val_predict(HistGradientBoostingClassifier(**params), X, y, cv=cv, groups=groups,
                                method="predict_proba")[:, 1]
        self.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof, y)
        self.booster = HistGradientBoostingClassifier(**params).fit(X, y)
        return self

    def predict_batch(self, X: np.ndarray) -> np.ndarray:
        return self.calibrator.predict(self.booster.predict_proba(X)[:, 1])

    def predict(self, feats: dict) -> float | None:
        if not self.ready:
            return None
        return float(self.predict_batch(to_vector(feats)[None, :])[0])

    def explain(self, feats: dict, top: int = 5) -> list[dict]:
        if self.booster is None:
            return []
        try:
            import shap

            if self._explainer is None:
                self._explainer = shap.TreeExplainer(self.booster)
            sv = np.asarray(self._explainer.shap_values(to_vector(feats)[None, :]))
            sv = sv.reshape(-1)[-len(FEATURE_NAMES):]
        except Exception:  # SHAP optional: fall back to nothing rather than fake values
            return []
        order = np.argsort(-np.abs(sv))[:top]
        return [{"feature": FEATURE_NAMES[i], "value": round(float(feats.get(FEATURE_NAMES[i], 0)), 2),
                 "contribution": round(float(sv[i]), 3)} for i in order]

    def save(self, path: Path = MODELS_DIR / "risk_forecaster.joblib") -> None:
        joblib.dump({"booster": self.booster, "calibrator": self.calibrator, "meta": self.meta}, path)

    @classmethod
    def load(cls, path: Path = MODELS_DIR / "risk_forecaster.joblib") -> "RiskForecaster":
        if not Path(path).exists():
            return cls()
        d = joblib.load(path)
        return cls(d["booster"], d.get("calibrator"), d.get("meta"))
