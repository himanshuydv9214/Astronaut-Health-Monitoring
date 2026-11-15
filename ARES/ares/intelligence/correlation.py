"""Physiological correlation engine.

Two complementary mechanisms:

1. Named co-deviation patterns. Each is a transparent rule over the
   personal deviation scores (zb), encoding well-known physiological
   couplings (e.g., desaturation with compensatory tachycardia/tachypnoea).
   A match yields a *potential risk category* used to retrieve protocols -
   it is a hypothesis for the crew medical officer, never a diagnosis.

2. Rolling cross-correlation of deviation series between signal pairs
   over the last 60 min, shown in the UI so the crew can see which
   signals are moving together.
"""

from __future__ import annotations

from collections import deque
from itertools import combinations

import numpy as np

from ares.config import VITAL_KEYS

# Rules use SIGNED personal z-scores (s): e.g. "tachypnoea" means RR ABOVE this person's
# usual, not merely far from it. zb (bad-direction) is only used for one-sided signals.
PATTERNS = [
    {"id": "hypoxaemia", "name": "Desaturation with compensatory response",
     "rule": lambda z, x: z["spo2"] <= -3 and (z["hr"] >= 2 or z["rr"] >= 2),
     "signals": ["spo2", "hr", "rr"]},
    {"id": "febrile", "name": "Thermal + cardiovascular (febrile/inflammatory-like) pattern",
     "rule": lambda z, x: z["temp"] >= 3 and z["hr"] >= 2,
     "signals": ["temp", "hr", "rr"]},
    {"id": "hypovolaemia", "name": "Tachycardia with falling blood pressure (fluid-loss-like) pattern",
     "rule": lambda z, x: z["hr"] >= 2.5 and x.get("sbp_low", 0) >= 2.5,
     "signals": ["hr", "sbp", "dbp"]},
    {"id": "arrhythmia", "name": "Irregular rhythm pattern (R-R irregularity)",
     "rule": lambda z, x: (x.get("rr_cv", 0) > 0.12 and z["hr"] >= 2) or (x.get("hrv_high", 0) >= 4 and z["hr"] >= 3),
     "signals": ["hr", "hrv_rmssd"]},
    {"id": "respiratory", "name": "Tachypnoea with mild desaturation",
     "rule": lambda z, x: z["rr"] >= 3 and z["spo2"] <= -1.5,
     "signals": ["rr", "spo2"]},
    {"id": "fatigue", "name": "Sleep debt with autonomic strain",
     "rule": lambda z, x: x.get("sleep_deficit_h", 0) >= 2 and (x.get("hrv_low", 0) >= 1.5 or z["hr"] >= 1.5),
     "signals": ["hrv_rmssd", "hr"]},
]


def match_patterns(zb: dict, st: dict, feats: dict) -> list[dict]:
    zraw = st["z"]
    signed = {k: (zraw.get(k) or 0.0) for k in VITAL_KEYS}
    extra = {
        "rr_cv": feats.get("rr_cv", 0.0),
        "sleep_deficit_h": feats.get("sleep_deficit_h", 0.0),
        "hrv_low": -(zraw.get("hrv_rmssd") or 0.0),
        "hrv_high": (zraw.get("hrv_rmssd") or 0.0),
        "sbp_low": -(zraw.get("sbp") or 0.0),
    }
    out = []
    for p in PATTERNS:
        try:
            if p["rule"](signed, extra):
                out.append({"id": p["id"], "name": p["name"],
                            "evidence": {s: round(zraw.get(s) or 0.0, 2) for s in p["signals"]}})
        except (KeyError, TypeError):
            continue
    return out


class RollingCorrelation:
    PAIRS = [("hr", "rr"), ("spo2", "rr"), ("spo2", "hr"), ("temp", "hr"), ("hr", "sbp"), ("hr", "hrv_rmssd")]

    def __init__(self, window: int = 60):
        self.buf: deque = deque(maxlen=window)

    def update(self, st: dict) -> None:
        self.buf.append({k: (st["values"][k] - st["expected"][k]) if st["values"][k] is not None and st["age_min"][k] == 0
                         else np.nan for k in VITAL_KEYS})

    def matrix(self) -> dict:
        if len(self.buf) < 20:
            return {}
        out = {}
        for a, b in self.PAIRS:
            x = np.array([r[a] for r in self.buf], float)
            y = np.array([r[b] for r in self.buf], float)
            m = ~(np.isnan(x) | np.isnan(y))
            if m.sum() >= 15 and np.std(x[m]) > 0 and np.std(y[m]) > 0:
                out[f"{a}~{b}"] = round(float(np.corrcoef(x[m], y[m])[0, 1]), 2)
        return out


ALL_PAIRS = list(combinations(VITAL_KEYS, 2))
