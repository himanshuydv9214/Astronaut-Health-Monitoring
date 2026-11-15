"""Metrics, baseline, comparison and longitudinal trends for saved tests.

Wording rules (also tested):
  * Comparisons are OBSERVED differences between this astronaut's own saved tests. They are never a diagnosis.
  * The behavioral readiness level is a MODEL-GENERATED assessment and is always labelled as such.
  * A reaction-time result says nothing about brain structure.
  * Only metrics the test actually produced are reported; missing values stay missing (None), never filled in.
"""

from __future__ import annotations

import math
import statistics as stats

from ares.behavioral.pvt import FALSE_START_MS, LAPSE_MS, MIN_VALID_RESPONSES

BASELINE_N = 3                     # personal baseline = first 3 completed, scored tests of this astronaut
REL_SLOWER = 0.10                  # >= 10 % slower mean RT than baseline -> "slower" (observed)
REL_FASTER = -0.08
LAPSE_DELTA = 3
VAR_RATIO = 1.3
OBSERVED = "Observed in saved test results"
MODEL = "Model-generated assessment"


def pvt_metrics(trials: list[dict]) -> dict:
    """Recompute every PVT-B metric from the stored trials (single source of truth)."""
    resp = [t["rt_ms"] for t in trials if t["outcome"] in ("response", "lapse") and t["rt_ms"] is not None]
    false_starts = sum(1 for t in trials if t["outcome"] == "false_start")
    premature = sum(1 for t in trials if t["outcome"] == "premature")
    misses = sum(1 for t in trials if t["outcome"] == "miss")
    stimuli = sum(1 for t in trials if t["outcome"] != "premature")
    m = {"trials": stimuli, "responses": len(resp), "misses": misses, "false_starts": false_starts,
         "premature_no_stimulus": premature, "premature": premature + false_starts,
         "lapses": sum(1 for r in resp if r >= LAPSE_MS) + misses,
         "mean_rt_ms": None, "median_rt_ms": None, "fastest_ms": None, "slowest_ms": None, "sd_ms": None, "cv": None,
         "response_speed": None, "slowest10_speed": None,
         "thresholds": {"lapse_ms": LAPSE_MS, "false_start_ms": FALSE_START_MS, "miss_ms": 10000,
                        "min_valid_responses": MIN_VALID_RESPONSES}}
    if resp:
        mean = sum(resp) / len(resp)
        sd = stats.stdev(resp) if len(resp) > 1 else None
        speeds = sorted(1000.0 / r for r in resp)
        slow = speeds[: max(1, len(speeds) // 10)]
        m.update({"mean_rt_ms": round(mean, 1), "median_rt_ms": round(stats.median(resp), 1),
                  "fastest_ms": round(min(resp), 1), "slowest_ms": round(max(resp), 1),
                  "sd_ms": None if sd is None else round(sd, 1), "cv": None if sd is None else round(sd / mean, 3),
                  "response_speed": round(sum(speeds) / len(speeds), 3),
                  "slowest10_speed": round(sum(slow) / len(slow), 3)})
    return m


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def baseline_for(store, aid: str, test_type: str, exclude: str | None = None) -> dict:
    """Personal baseline: mean of the astronaut's first BASELINE_N completed, scored tests (all saved sessions)."""
    rows = [r for r in reversed(store.list(aid=aid, test_type=test_type, status="completed", limit=2000))
            if r["test_id"] != exclude and r["scored"]]
    base = rows[:BASELINE_N]
    if test_type != "pvt" or not base:
        return {"established": False, "n": len(base), "needed": BASELINE_N,
                "note": f"Personal baseline not established yet: needs {BASELINE_N} completed, scored tests "
                        f"({len(base)} so far)."}
    ms = [store.get(r["test_id"])["result"]["metrics"] for r in base]
    b = {k: _mean([m.get(k) for m in ms]) for k in ("mean_rt_ms", "median_rt_ms", "lapses", "sd_ms", "cv",
                                                     "response_speed", "premature")}
    b = {k: (round(v, 3) if v is not None else None) for k, v in b.items()}
    return {"established": len(base) >= BASELINE_N, "n": len(base), "needed": BASELINE_N, "values": b,
            "tests": [r["test_id"] for r in base],
            "note": ("Mean of this astronaut's first " + str(len(base)) + " completed, scored tests" +
                     ("" if len(base) >= BASELINE_N else f" (provisional: {BASELINE_N} needed)") + ".")}


def previous_for(store, aid: str, test_type: str, before: float, exclude: str) -> dict | None:
    for r in store.list(aid=aid, test_type=test_type, limit=2000):
        if r["test_id"] != exclude and r["started_at"] < before and r["status"] in ("completed", "legacy") and r["scored"]:
            full = store.get(r["test_id"])
            return {"test_id": r["test_id"], "started_at": r["started_at"], "mission_day": r["mission_day"],
                    "status": r["status"], "metrics": full["result"]["metrics"]}
    return None


def compare(m: dict, ref: dict | None) -> dict | None:
    if not ref or m.get("mean_rt_ms") is None:
        return None
    out = {}
    for k in ("mean_rt_ms", "median_rt_ms", "lapses", "sd_ms", "cv", "response_speed", "premature"):
        a, b = m.get(k), ref.get(k)
        if a is None or b is None:
            out[k] = None
            continue
        out[k] = {"current": a, "reference": b, "difference": round(a - b, 3),
                  "relative": None if not b else round((a - b) / b, 3)}
    return out


def interpret_pvt(m: dict, status: str, baseline: dict, previous: dict | None, scored: bool) -> list[dict]:
    """Plain-language reading of OBSERVED differences. Never a diagnosis."""
    out: list[dict] = []
    if status != "completed":
        out.append({"kind": "status", "s": "watch",
                    "text": f"This test was {status}, so it is kept in the record but not used for the personal "
                            "baseline or the alertness assessment."})
    if m.get("mean_rt_ms") is None:
        out.append({"kind": "data", "s": "unknown", "text": "No valid responses were recorded, so no reaction-time "
                                                             "result can be given."})
        return out
    if not scored:
        out.append({"kind": "data", "s": "unknown", "text": f"Fewer than {MIN_VALID_RESPONSES} valid responses - "
                                                             "shown for reference, not scored as a PVT-B."})
    ref = baseline.get("values") if baseline.get("n") else None
    if ref and ref.get("mean_rt_ms"):
        d = (m["mean_rt_ms"] - ref["mean_rt_ms"]) / ref["mean_rt_ms"]
        lab = "personal baseline" + ("" if baseline.get("established") else " (provisional)")
        if d >= REL_SLOWER or (ref.get("lapses") is not None and m["lapses"] >= ref["lapses"] + LAPSE_DELTA):
            out.append({"kind": "observed", "s": "watch",
                        "text": f"Slower than the {lab}: {m['mean_rt_ms']:.0f} vs {ref['mean_rt_ms']:.0f} ms average, "
                                f"{m['lapses']} vs {ref['lapses']:.1f} lapses. Consider sleep, workload and time of day; "
                                "repeat the test."})
        elif d <= REL_FASTER:
            out.append({"kind": "observed", "s": "good",
                        "text": f"Faster than the {lab}: {m['mean_rt_ms']:.0f} vs {ref['mean_rt_ms']:.0f} ms."})
        else:
            out.append({"kind": "observed", "s": "stable",
                        "text": f"Consistent with the {lab} ({m['mean_rt_ms']:.0f} vs {ref['mean_rt_ms']:.0f} ms)."})
        if m.get("sd_ms") and ref.get("sd_ms") and m["sd_ms"] > ref["sd_ms"] * VAR_RATIO:
            out.append({"kind": "observed", "s": "watch",
                        "text": f"Reaction times varied more than usual (spread {m['sd_ms']:.0f} vs "
                                f"{ref['sd_ms']:.0f} ms)."})
    else:
        out.append({"kind": "observed", "s": "stable", "text": baseline.get("note", "No personal baseline yet.")})
    if previous and previous["metrics"].get("mean_rt_ms"):
        pm = previous["metrics"]
        out.append({"kind": "observed", "s": "stable",
                    "text": f"Previous saved test: {pm['mean_rt_ms']:.0f} ms average, {pm['lapses']} lapses."})
    out.append({"kind": "note", "s": "stable",
                "text": "One test is never a diagnosis. A reaction-time result reflects alertness on the day; it says "
                        "nothing about brain structure."})
    return out


def _fit(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pts) < 3:
        return None
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    ss_res = sum((p[1] - (my + slope * (p[0] - mx))) ** 2 for p in pts)
    ss_tot = sum((p[1] - my) ** 2 for p in pts)
    return {"slope": slope, "r2": None if ss_tot == 0 else round(1 - ss_res / ss_tot, 3), "n": len(pts)}


def trends(store, aid: str, engine=None) -> dict:
    """Longitudinal reaction-test analysis across ALL saved sessions (completed + scored tests only)."""
    rows = [r for r in reversed(store.list(aid=aid, test_type="pvt", limit=2000))
            if r["status"] in ("completed", "legacy") and r["scored"]]
    series = []
    for r in rows:
        m = store.get(r["test_id"])["result"]["metrics"]
        series.append({"test_id": r["test_id"], "started_at": r["started_at"], "mission_day": r["mission_day"],
                       "status": r["status"], "mean_rt_ms": m.get("mean_rt_ms"), "median_rt_ms": m.get("median_rt_ms"),
                       "lapses": m.get("lapses"), "sd_ms": m.get("sd_ms"), "cv": m.get("cv"),
                       "response_speed": m.get("response_speed")})
    idx = list(range(len(series)))
    obs = []
    for key, label, unit, worse_up in (("mean_rt_ms", "Average reaction time", "ms", True),
                                       ("lapses", "Lapses", "", True), ("sd_ms", "Response-time variability (SD)", "ms", True)):
        f = _fit(idx, [s[key] for s in series])
        if f is None:
            continue
        per = f["slope"]
        first, last = series[0][key], series[-1][key]
        direction = ("increasing" if per > 0 else "decreasing") if abs(per) > 1e-9 else "flat"
        meaning = "slower / less consistent" if (per > 0) == worse_up else "faster / more consistent"
        notable = (key == "mean_rt_ms" and first and abs(last - first) / first >= REL_SLOWER) or \
                  (key == "lapses" and abs(last - first) >= LAPSE_DELTA) or \
                  (key == "sd_ms" and first and last and (last / first >= VAR_RATIO or first / last >= VAR_RATIO))
        obs.append({"metric": key, "label": label, "unit": unit, "per_test": round(per, 2), "n": f["n"],
                    "r2": f["r2"], "first": first, "latest": last, "direction": direction,
                    "notable": bool(notable), "category": OBSERVED,
                    "text": f"{label} {direction} by {abs(per):.1f}{(' ' + unit) if unit else ''} per test over "
                            f"{f['n']} tests ({first} → {last}){' - ' + meaning if notable else ''}."})
    model = None
    if engine is not None and aid in getattr(engine, "behavior", {}):
        a = engine.behavior[aid].assess()
        model = {"category": MODEL, "level": a["level"], "label": a["label"], "note": a.get("note"),
                 "flagged": a.get("flagged", []),
                 "text": "Behavioral readiness model (combines reaction-test speed, fatigue ratings, sleep and mood "
                         "against the astronaut's own baseline). It is an estimate, not a measurement."}
    return {"astronaut_id": aid, "n_tests": len(series), "series": series, "observed": obs, "model": model,
            "baseline": baseline_for(store, aid, "pvt"),
            "note": "Observed trends are straight-line fits through this astronaut's saved, completed tests. They "
                    "describe what was measured; they are not predictions and not a diagnosis."
            + ("" if len(series) >= 3 else " At least 3 completed tests are needed to compute a trend.")}


def finite(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)
