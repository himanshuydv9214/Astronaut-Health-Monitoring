"""Astronaut Health Digital Twin.

A continuously updated computational health profile per astronaut:
personal context-conditioned baselines (Bayesian), per-signal trend
state (Kalman), signal-quality state, sleep accounting, a longitudinal
daily summary relative to the pre-mission baseline, and an event timeline.

This is a statistical profile of *this person's own data*. It is not a
mechanistic physiological model and is not clinically validated.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from ares.config import DETECTION, PARAMS, VITAL_KEYS
from ares.processing.quality import SignalQualityMonitor, sensor_health
from ares.simulation.physiology import SimSample
from ares.twin.baseline import ContextEstimator, PersonalBaseline
from ares.twin.trend import LocalLinearTrend

HOLD_MIN = {"sbp": 20, "dbp": 20}   # intermittent cuff values remain valid this long


class DigitalTwin:
    def __init__(self, astronaut_id: str, history_len: int = 1440 * 2):
        self.id = astronaut_id
        self.baseline = PersonalBaseline()
        self.ctx_est = ContextEstimator()
        self.quality = SignalQualityMonitor()
        self.trends = {k: LocalLinearTrend() for k in VITAL_KEYS}
        self.history: deque = deque(maxlen=history_len)
        self.sleep_window: deque = deque(maxlen=1440)
        self.daily: dict[int, dict] = {}
        self.hourly: dict[int, dict] = {}       # resting values per mission hour -> drift / long-term tables
        self.timeline: list[dict] = []
        self._held: dict[str, tuple[float, float, dict]] = {}
        self.last_state: dict | None = None

    # ------------------------------------------------------------------
    def observe(self, s: SimSample, learn: bool = True) -> dict:
        ctx = self.ctx_est.update(s.activity_counts)
        ecg_sqi = s.ecg_proc["quality"] if s.ecg_proc else None
        clean, q, faults, meta = self.quality.assess(s.readings, s.device, s.pulse_rate, ecg_sqi, s.t_min)
        z, expected, band, slope, slope_sd, unc, values, age = {}, {}, {}, {}, {}, {}, {}, {}
        for k in VITAL_KEYS:
            x = clean.get(k, np.nan)
            valid = x is not None and not np.isnan(x) and q[k] >= DETECTION.min_quality
            if valid:
                sc = self.baseline.score(k, ctx, x)
                if learn:
                    self.baseline.update(k, ctx, x, sc["z"])
                if k in HOLD_MIN:
                    self._held[k] = (s.t_min, x, sc)
                values[k], age[k] = float(x), 0.0
            elif k in self._held and s.t_min - self._held[k][0] <= HOLD_MIN[k]:
                t_meas, x_old, sc = self._held[k]
                values[k], age[k] = x_old, s.t_min - t_meas
                valid = True
            else:
                sc = self.baseline.score(k, ctx, self.baseline.post[(k, ctx)].mu)
                values[k], age[k] = None, None
            expected[k] = sc["expected"]
            band[k] = (sc["expected"] - 2 * sc["scale"], sc["expected"] + 2 * sc["scale"])
            unc[k] = sc["uncertainty"]
            z[k] = sc["z"] if valid else None
            dev = (values[k] - sc["expected"]) if (valid and age[k] == 0) else None
            _, sl, sd = self.trends[k].step(dev, sc["scale"] ** 2)
            slope[k], slope_sd[k] = sl, sd

        self.sleep_window.append(1 if ctx == "sleep" else 0)
        sleep_h = sum(self.sleep_window) / 60.0 if len(self.sleep_window) >= 720 else None
        state = {
            "t": s.t_min, "astronaut_id": self.id, "context": ctx, "values": values, "age_min": age,
            "quality": q, "faults": faults, "sensor_health": sensor_health(faults),
            "hr_source": meta["hr_source"], "z": z, "expected": expected, "band": band,
            "slope_h": slope, "slope_sd_h": slope_sd, "uncertainty": unc, "sleep_h_24h": sleep_h,
            "pulse_rate": s.pulse_rate, "dose_rate": s.dose_rate_msv_day,
            "ecg_extra": ({k: s.ecg_proc.get(k) for k in ("sdnn", "pnn50", "rr_cv", "n_beats", "quality")}
                          if s.ecg_proc else None),
        }
        self.history.append(state)
        self._daily(state)
        self.last_state = state
        return state

    # ------------------------------------------------------------------
    def _daily(self, st: dict) -> None:
        day = int(st["t"] // 1440)
        d = self.daily.setdefault(day, {"n": 0, "rest": {k: [] for k in VITAL_KEYS}, "sleep_min": 0})
        d["n"] += 1
        if st["context"] == "sleep":
            d["sleep_min"] += 1
        if st["context"] == "rest":
            h = self.hourly.setdefault(int(st["t"] // 60), {k: [] for k in VITAL_KEYS})
            for k in VITAL_KEYS:
                v = st["values"][k]
                if v is not None and st["age_min"].get(k) == 0:
                    d["rest"][k].append(v)
                    h[k].append(v)
            if len(self.hourly) > 24 * 60:
                for old in sorted(self.hourly)[: len(self.hourly) - 24 * 60]:
                    del self.hourly[old]

    def longitudinal(self) -> list[dict]:
        out = []
        for day in sorted(self.daily):
            d = self.daily[day]
            row = {"day": day, "sleep_h": round(d["sleep_min"] / 60, 2)}
            for k in VITAL_KEYS:
                vals = d["rest"][k]
                row[k] = round(float(np.mean(vals)), 2) if vals else None
            out.append(row)
        return out

    def drift_summary(self) -> dict:
        out = {}
        for k in VITAL_KEYS:
            dr = self.baseline.drift_from_premission(k, "rest")
            if dr is not None:
                out[k] = {"drift": round(dr, 3), "unit": PARAMS[k].unit}
        return out

    def add_event(self, t: float, kind: str, text: str, level: int = 0) -> None:
        self.timeline.append({"t": t, "kind": kind, "text": text, "level": level})
        self.timeline = self.timeline[-300:]
