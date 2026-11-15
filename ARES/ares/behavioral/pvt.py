"""PVT-B: 3-minute Psychomotor Vigilance Test (brief) scoring.

Implements the scoring used for the ISS "Reaction Self Test" (Jones, Basner,
Mollicone, Mott, Dinges, SLEEP 2022, PMC8919197) and the original PVT-B
validation (Basner, Mollicone & Dinges, Acta Astronautica 69:949, 2011):

  * test duration 3 min, inter-stimulus interval 2-5 s
  * lapse          = RT >= 355 ms   (reduced from 500 ms for the 3-min version)
  * false start    = response with no stimulus, or RT < 130 ms
  * primary metric = mean response speed = mean(1000 / RT)  [1/s]
    (the outcome most sensitive to sleep loss in both papers)

The dashboard runs a real PVT-B in the browser; the simulator generates
synthetic results for the fictional crew. Both are scored here.
"""

from __future__ import annotations

import numpy as np

LAPSE_MS = 355.0
FALSE_START_MS = 130.0
DURATION_S = 180
ISI_RANGE_S = (2.0, 5.0)
MIN_VALID_RESPONSES = 20     # fewer -> test considered invalid (interrupted)


def score_pvt(rts_ms: list[float], anticipations: int = 0) -> dict:
    """Score one PVT-B.

    rts_ms        : reaction times for responses to stimuli (ms)
    anticipations : key presses with no stimulus on screen (counted as false starts)
    """
    rt = np.asarray([r for r in rts_ms if r is not None and np.isfinite(r)], float)
    fs_fast = int(np.sum(rt < FALSE_START_MS))
    valid = rt[rt >= FALSE_START_MS]
    false_starts = fs_fast + int(anticipations)
    if len(valid) < MIN_VALID_RESPONSES:
        return {"valid": False, "n": int(len(valid)), "false_starts": false_starts,
                "reason": f"only {len(valid)} valid responses (need {MIN_VALID_RESPONSES})"}
    speed = 1000.0 / valid
    lapses = int(np.sum(valid >= LAPSE_MS))
    slow10 = np.sort(speed)[: max(1, len(speed) // 10)]
    return {
        "valid": True,
        "n": int(len(valid)),
        "mean_rt_ms": round(float(valid.mean()), 1),
        "median_rt_ms": round(float(np.median(valid)), 1),
        "response_speed": round(float(speed.mean()), 3),          # primary outcome, 1/s
        "slowest10_speed": round(float(slow10.mean()), 3),
        "lapses": lapses,
        "false_starts": false_starts,
        "errors": lapses + false_starts,
        "thresholds": {"lapse_ms": LAPSE_MS, "false_start_ms": FALSE_START_MS},
    }


def pvt_stats(rts_ms: list[float], anticipations: int = 0, misses: int = 0) -> dict:
    """Descriptive results for display (all responses to stimuli, ms). Misses = no response within 10 s."""
    rt = np.asarray([r for r in rts_ms if r is not None and np.isfinite(r)], float)
    premature = int(np.sum(rt < FALSE_START_MS)) + int(anticipations)
    v = rt[rt >= FALSE_START_MS]
    if not len(v):
        return {"trials": int(len(rt) + misses), "responses": 0, "premature": premature, "misses": int(misses),
                "lapses": 0, "mean_rt_ms": None, "median_rt_ms": None, "fastest_ms": None, "slowest_ms": None,
                "sd_ms": None, "cv": None, "response_speed": None,
                "thresholds": {"lapse_ms": LAPSE_MS, "false_start_ms": FALSE_START_MS, "miss_ms": 10000}}
    return {
        "trials": int(len(rt) + misses), "responses": int(len(v)), "premature": premature, "misses": int(misses),
        "lapses": int(np.sum(v >= LAPSE_MS)) + int(misses),
        "mean_rt_ms": round(float(v.mean()), 1), "median_rt_ms": round(float(np.median(v)), 1),
        "fastest_ms": round(float(v.min()), 1), "slowest_ms": round(float(v.max()), 1),
        "sd_ms": round(float(v.std(ddof=1)), 1) if len(v) > 1 else 0.0,
        "cv": round(float(v.std(ddof=1) / v.mean()), 3) if len(v) > 1 else 0.0,
        "response_speed": round(float((1000.0 / v).mean()), 3),
        "rts_ms": [round(float(x), 1) for x in rt],
        "thresholds": {"lapse_ms": LAPSE_MS, "false_start_ms": FALSE_START_MS, "miss_ms": 10000},
    }
