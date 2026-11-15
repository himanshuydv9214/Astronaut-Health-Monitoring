"""Health changes over time and gradual drift from an astronaut's own normal.

A *sudden* change (minutes) is handled by the alert engine. *Drift* is a slow, sustained shift of the RESTING level
over hours to days - e.g. resting heart rate creeping up with deconditioning or fatigue. It is usually not an
emergency, but it is worth watching.

Method (per vital sign, resting context only):
  * hourly resting means from the digital twin
  * reference = the astronaut's own baseline-acquisition period (mean and SD of hourly resting means)
  * current   = mean of the last 3 hours that have resting data
  * drift z   = (current - reference mean) / reference SD of hourly means
  * duration  = consecutive recent hours whose mean is beyond +/-2 SD in the same direction
  * status    : stable (|z| < 2) / watch (|z| >= 2 for < 3 h) / gradual change (|z| >= 2 for >= 3 h, built up over
                more than 1 h) / sudden change (deviation appeared within the last hour -> see alerts)
"""

from __future__ import annotations

import numpy as np

from ares.config import PARAMS, VITAL_KEYS

ORDER = ["hr", "hrv_rmssd", "sbp", "dbp", "spo2", "rr", "temp"]
PLAIN = {"hr": "Resting heart rate", "hrv_rmssd": "Heart rate variability (HRV)", "sbp": "Blood pressure (systolic)",
         "dbp": "Blood pressure (diastolic)", "spo2": "Blood oxygen level (SpO₂)", "rr": "Breathing rate",
         "temp": "Body temperature (estimated)"}
MIN_SAMPLES_PER_HOUR = 5


def _hour_means(twin, k, h0=None, h1=None):
    out = []
    for h in sorted(twin.hourly):
        if (h0 is not None and h < h0) or (h1 is not None and h >= h1):
            continue
        v = twin.hourly[h][k]
        if len(v) >= (1 if k in ("sbp", "dbp") else MIN_SAMPLES_PER_HOUR):
            out.append((h, float(np.mean(v)), len(v)))
    return out


def health_trends(twin, ref_end_min: float, now_min: float) -> dict:
    ref_end_h = int(ref_end_min // 60)
    now_h = int(now_min // 60)
    rows = []
    for k in ORDER:
        if k not in VITAL_KEYS:
            continue
        ref = _hour_means(twin, k, h1=ref_end_h)
        live = _hour_means(twin, k, h0=ref_end_h)
        unit = PARAMS[k].unit.replace("degC", "°C")
        base = {"key": k, "label": PLAIN.get(k, PARAMS[k].label), "unit": unit,
                "source": "measured" if PARAMS[k].measured else "derived (estimated)", "sensor": PARAMS[k].sensor}
        if len(ref) < 3:
            rows.append(base | {"status": "insufficient", "note": "Not enough resting reference data yet"})
            continue
        rm = float(np.mean([m for _, m, _ in ref]))
        rsd = max(float(np.std([m for _, m, _ in ref], ddof=1)), 1e-3 * max(abs(rm), 1.0))
        if not live:
            rows.append(base | {"baseline": round(rm, 2), "baseline_sd": round(rsd, 2), "status": "insufficient",
                                "note": "No resting measurements since the baseline period"})
            continue
        last3 = live[-3:]
        cur = float(np.mean([m for _, m, _ in last3]))
        z = (cur - rm) / rsd
        sign = 1 if z >= 0 else -1
        dur = 0
        for h, m, _ in reversed(live):
            zz = (m - rm) / rsd
            if abs(zz) >= 2 and (1 if zz >= 0 else -1) == sign:
                dur += 1
            else:
                break
        first_dev_h = live[-dur][0] if dur else None
        onset_h = (now_h - first_dev_h + 1) if first_dev_h is not None else 0
        # how fast did it appear? hourly means just before the deviating run
        if abs(z) < 2:
            status = "stable"
        elif onset_h <= 1:
            status = "sudden"
        elif dur >= 3:
            status = "gradual"
        else:
            status = "watch"
        recent_hours = [h for h, _, _ in live if h > now_h - 6]
        n_recent = sum(n for h, _, n in live if h > now_h - 6)
        quality = "good" if len(recent_hours) >= 3 else "limited" if recent_hours else "stale"
        series = live[-24:]
        rows.append(base | {
            "baseline": round(rm, 2), "baseline_sd": round(rsd, 2), "current": round(cur, 2),
            "change": round(cur - rm, 2), "change_pct": round((cur - rm) / rm * 100, 1) if rm else None,
            "z": round(z, 2), "direction": "up" if cur > rm else "down" if cur < rm else "flat",
            "duration_h": dur, "status": status, "quality": quality, "n_recent": int(n_recent),
            "last_updated_min": float(live[-1][0] * 60 + 59),
            "series": [{"hour": h, "mean": round(m, 2), "n": n} for h, m, n in series],
            "slope_per_day": round(float(np.polyfit([h for h, _, _ in series], [m for _, m, _ in series], 1)[0] * 24), 3)
            if len(series) >= 4 else None,
        })
    return {"rows": rows, "reference": f"own resting values during baseline acquisition (first {ref_end_h} h)",
            "method": __doc__.split("Method")[1].strip(), "now_min": now_min}
