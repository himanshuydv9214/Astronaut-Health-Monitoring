"""Stream-level signal-quality assessment and sensor-fault identification.

Quality is estimated from the data and device status, never from the
simulator's ground truth. Checks (each documented with its rationale):

1. Missing value     - NaN. For BP, NaN between scheduled cuff readings is
                       expected and is reported as 'not_scheduled'.
2. Plausibility      - reading outside the physically possible sensor range.
3. Flatline          - SpO2 and oximeter pulse rate both frozen for >= 10 min.
                       Real pulse rate is never constant to 1 bpm that long.
4. Device status     - low perfusion index (<0.6) marks oximeter motion
                       artefact; ECG lead contact flag.
5. ECG SQI           - from processing.ecg.ecg_quality (template corr., kurtosis).
6. Redundancy        - ECG-derived HR vs oximeter pulse rate. Disagreement
                       > 15 bpm lowers trust; if ECG is poor and the oximeter
                       is good, HR falls back to pulse rate (sensor redundancy).
"""

from __future__ import annotations

from collections import deque

import numpy as np

from ares.config import PARAMS, VITAL_KEYS

FLATLINE_MIN = 10
PI_LOW = 0.6
HR_DISAGREE_BPM = 15.0


class SignalQualityMonitor:
    def __init__(self):
        self.spo2_hist: deque = deque(maxlen=FLATLINE_MIN)
        self.pr_hist: deque = deque(maxlen=FLATLINE_MIN)

    def assess(self, readings: dict, device: dict, pulse_rate: float, ecg_sqi: float | None = None,
               t_min: float | None = None) -> tuple[dict, dict, list[str], dict]:
        """Return (clean_readings, quality[0..1], faults, meta)."""
        q = {k: 1.0 for k in VITAL_KEYS}
        faults: list[str] = []
        clean = dict(readings)
        meta = {"hr_source": "ecg"}

        for k in VITAL_KEYS:
            v = readings.get(k, np.nan)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                q[k] = 0.0
                clean[k] = np.nan
                if k not in ("sbp", "dbp"):
                    faults.append(f"{k}:missing")
                continue
            lo, hi = PARAMS[k].plausible
            if not (lo <= v <= hi):
                q[k] = 0.0
                clean[k] = np.nan
                faults.append(f"{k}:implausible")

        # oximeter flatline
        sp, pr = readings.get("spo2", np.nan), pulse_rate
        self.spo2_hist.append(sp)
        self.pr_hist.append(None if pr is None or np.isnan(pr) else round(pr))
        if len(self.spo2_hist) == FLATLINE_MIN and len(set(self.spo2_hist)) == 1 \
                and None not in self.pr_hist and len(set(self.pr_hist)) == 1:
            q["spo2"] = 0.05
            faults.append("spo2:flatline")

        if device.get("spo2_perfusion", 3.0) < PI_LOW and q["spo2"] > 0:
            q["spo2"] = min(q["spo2"], 0.3)
            faults.append("spo2:low_perfusion_artifact")

        ecg_ok = device.get("ecg_contact", 1.0) >= 0.5
        if not ecg_ok:
            q["hr"] = q["hrv_rmssd"] = 0.0
            faults.append("ecg:lead_off")
        elif ecg_sqi is not None:
            q["hr"] = min(q["hr"], ecg_sqi)
            q["hrv_rmssd"] = min(q["hrv_rmssd"], ecg_sqi)
            if ecg_sqi < 0.5:
                faults.append("ecg:poor_quality")

        pr_ok = pr is not None and not np.isnan(pr) and q["spo2"] >= 0.6
        hr = clean.get("hr", np.nan)
        if pr_ok and not np.isnan(hr) and q["hr"] > 0 and abs(hr - pr) > HR_DISAGREE_BPM:
            faults.append("hr:ecg_oximeter_disagreement")
            q["hr"] = min(q["hr"], 0.5)
        if q["hr"] < 0.5 and pr_ok:
            clean["hr"] = float(pr)
            q["hr"] = 0.75
            meta["hr_source"] = "oximeter (fallback)"
            clean["hrv_rmssd"] = np.nan  # HRV cannot be derived from 1/min pulse rate
            q["hrv_rmssd"] = 0.0
        if q["hr"] == 0.0:
            clean["hr"] = np.nan
            clean["hrv_rmssd"] = np.nan

        for k in VITAL_KEYS:
            if q[k] < 0.3:
                clean[k] = np.nan if q[k] == 0 else clean[k]
        return clean, q, faults, meta


def sensor_health(faults: list[str]) -> str:
    if any(f.endswith(("flatline", "lead_off", "implausible")) for f in faults):
        return "FAULT"
    if faults:
        return "DEGRADED"
    return "OK"
