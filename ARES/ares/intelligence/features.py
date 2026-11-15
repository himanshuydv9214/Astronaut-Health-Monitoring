"""Feature construction for the ML models.

Features live in the astronaut's own *deviation space* (z-scores against
the personal context-conditioned baseline). This normalises across
individuals, which is what allows models trained on one set of people to
be evaluated on different people (astronaut-level split).

zb_k = bad-direction deviation: z for "high is bad", -z for "low is bad",
|z| for two-sided signals. Missing/low-quality -> 0 plus a quality feature.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from ares.config import PARAMS, VITAL_KEYS

CONTEXTS = ("sleep", "rest", "exercise", "recovery")


def bad_dir_z(key: str, z: float | None) -> float:
    if z is None or np.isnan(z):
        return 0.0
    d = PARAMS[key].bad_direction
    v = abs(z) if d == 0 else z * d
    return float(np.clip(v, -10, 15))


FEATURE_NAMES: list[str] = (
    [f"zb_{k}" for k in VITAL_KEYS]
    + [f"zb10_{k}" for k in VITAL_KEYS]
    + [f"zb30_{k}" for k in VITAL_KEYS]
    + [f"slope_{k}" for k in VITAL_KEYS]
    + ["zb_max", "n_params_z2", "n_systems_z2", "sleep_deficit_h", "min_quality", "rr_cv"]
    + [f"ctx_{c}" for c in CONTEXTS]
)

ANOMALY_FEATURES = [f"zb_{k}" for k in VITAL_KEYS] + [f"zb10_{k}" for k in VITAL_KEYS]


class FeatureBuilder:
    def __init__(self):
        self.buf: deque = deque(maxlen=30)
        self.sleep_norm_h = 8.0

    def build(self, st: dict) -> dict[str, float]:
        zb = {k: bad_dir_z(k, st["z"].get(k)) for k in VITAL_KEYS}
        self.buf.append(zb)
        arr = {k: np.array([b[k] for b in self.buf]) for k in VITAL_KEYS}
        f: dict[str, float] = {}
        for k in VITAL_KEYS:
            f[f"zb_{k}"] = zb[k]
            f[f"zb10_{k}"] = float(arr[k][-10:].mean())
            f[f"zb30_{k}"] = float(arr[k].mean())
            # standardised slope (baseline-sd per hour), bad direction positive
            d = PARAMS[k].bad_direction
            scale = max((st["band"][k][1] - st["band"][k][0]) / 4.0, 1e-6)
            sl = st["slope_h"][k] / scale
            f[f"slope_{k}"] = float(np.clip(abs(sl) if d == 0 else sl * d, -20, 20))
        f["zb_max"] = max(zb.values())
        f["n_params_z2"] = float(sum(v > 2 for v in zb.values()))
        f["n_systems_z2"] = float(len({PARAMS[k].system for k, v in zb.items() if v > 2}))
        sl = st.get("sleep_h_24h")
        f["sleep_deficit_h"] = float(max(0.0, self.sleep_norm_h - sl)) if sl is not None else 0.0
        f["min_quality"] = float(min(st["quality"][k] for k in ("hr", "spo2", "rr", "temp")))
        ex = st.get("ecg_extra") or {}
        f["rr_cv"] = float(ex.get("rr_cv") or 0.0)
        for c in CONTEXTS:
            f[f"ctx_{c}"] = 1.0 if st["context"] == c else 0.0
        return f


def to_vector(f: dict, names: list[str] = FEATURE_NAMES) -> np.ndarray:
    return np.array([f.get(n, 0.0) for n in names], dtype=float)
