"""NEWS2 - National Early Warning Score 2 (Royal College of Physicians, 2017).

Implemented as a PUBLISHED, transparent comparator ("what an Earth hospital
track-and-trigger score would say"). NEWS2 was validated on resting hospital
patients, not astronauts, so ARES only computes it in sleep/rest contexts and
uses it for comparison and as one input to explanation, not as ground truth.
Consciousness level and supplemental-oxygen status are not sensed here and
are assumed 'Alert' / 'room air' (stated in the output).
"""

from __future__ import annotations

import math


def _band(v, bands):
    for lo, hi, pts in bands:
        if lo <= v <= hi:
            return pts
    return 0


RR = [(-math.inf, 8, 3), (9, 11, 1), (12, 20, 0), (21, 24, 2), (25, math.inf, 3)]
SPO2 = [(-math.inf, 91, 3), (92, 93, 2), (94, 95, 1), (96, math.inf, 0)]
SBP = [(-math.inf, 90, 3), (91, 100, 2), (101, 110, 1), (111, 219, 0), (220, math.inf, 3)]
HR = [(-math.inf, 40, 3), (41, 50, 1), (51, 90, 0), (91, 110, 1), (111, 130, 2), (131, math.inf, 3)]
TEMP = [(-math.inf, 35.0, 3), (35.1, 36.0, 1), (36.1, 38.0, 0), (38.1, 39.0, 1), (39.1, math.inf, 2)]


def news2(values: dict) -> dict | None:
    """values: dict with rr, spo2, sbp, hr, temp (None allowed)."""
    parts = {}
    for key, bands, rnd in (("rr", RR, 0), ("spo2", SPO2, 0), ("sbp", SBP, 0), ("hr", HR, 0), ("temp", TEMP, 1)):
        v = values.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        parts[key] = _band(round(v, rnd) if rnd else round(v), bands)
    if len(parts) < 4:
        return None
    total = sum(parts.values())
    if total >= 7:
        risk = "high"
    elif total >= 5:
        risk = "medium"
    elif any(p == 3 for p in parts.values()):
        risk = "low-medium"
    else:
        risk = "low"
    return {"score": total, "risk": risk, "parts": parts, "assumed": "alert, room air"}


def news2_level(n: dict | None) -> int:
    """Map NEWS2 risk to the ARES 0-3 scale for baseline comparison."""
    if not n:
        return 0
    return {"low": 0, "low-medium": 1, "medium": 2, "high": 3}[n["risk"]] if n["score"] > 0 else 0
