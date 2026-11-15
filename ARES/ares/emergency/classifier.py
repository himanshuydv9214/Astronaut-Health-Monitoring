"""Hierarchical emergency classification (Level 0-3).

    0 Normal | 1 Observation required | 2 Medical assessment required | 3 Critical emergency

Deliberately a transparent, deterministic rule system rather than a learned
classifier: (1) there is no real labelled astronaut emergency data to learn
from, (2) every escalation must be auditable by the crew medical officer and
flight surgeons, (3) behaviour under sensor failure must be guaranteed.
ML outputs (anomaly score, risk forecast) can raise a level to 1
(observation) but can never by themselves declare a level 2/3 emergency.

Inputs considered (as required by the design brief):
  severity of deviation  -> personal z bands + absolute limits
  duration               -> per-signal persistence counters
  rate of deterioration  -> Kalman slope projected to an absolute limit
  number of systems      -> distinct physiological systems involved
  sensor reliability     -> quality gating; faulted channels never escalate
  individual history     -> personal baseline (not population ranges)
  model uncertainty      -> baseline uncertainty and corroboration -> confidence
Thresholds are engineering choices for the prototype (config.DetectionConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ares.config import DETECTION, PARAMS, VITAL_KEYS
from ares.intelligence.features import bad_dir_z

LEVEL_LABELS = {0: "Normal", 1: "Observation required", 2: "Medical assessment required",
                3: "Critical emergency"}

# Critical "act now" limits (more extreme than ParamSpec hard limits).
CRITICAL = {"spo2": (85, None), "hr": (35, 160), "rr": (6, 35), "sbp": (80, None), "temp": (None, 39.5)}
EXERCISE_EXEMPT = {"hr", "rr", "sbp", "dbp", "temp"}   # absolute hard limits not applied during exercise
INTERMITTENT = ("sbp", "dbp")   # spot-check (cuff) channels: persistence counted in measurements


@dataclass
class Classification:
    level: int
    label: str
    candidate_level: int
    reasons: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)       # key -> {sev, z, value, expected, sustained_min}
    systems: list[str] = field(default_factory=list)
    deteriorating: list[str] = field(default_factory=list)
    confidence: float = 0.0
    confidence_label: str = "low"
    sensor_alert: bool = False
    verify_readings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class EmergencyClassifier:
    def __init__(self, cfg=DETECTION):
        self.cfg = cfg
        self.counts = {k: [0, 0, 0, 0] for k in VITAL_KEYS}   # minutes sustained at >= sev 1..3
        self.level = 0
        self._lower_since: int = 0
        self._meas = {k: 0 for k in INTERMITTENT}
        self._fault_min = {k: 0 for k in VITAL_KEYS}
        self._corroborated: dict[str, bool] = {}
        self._meas_sev: dict[str, list[int]] = {k: [] for k in INTERMITTENT}

    # ------------------------------------------------------------------
    def _severity(self, k: str, st: dict) -> int:
        z, v = st["z"].get(k), st["values"].get(k)
        self._corroborated[k] = False
        if z is None or v is None:
            return 0
        zb = bad_dir_z(k, z)
        sev = 0
        if zb >= self.cfg.z_mild:
            sev = 1
        if zb >= self.cfg.z_moderate:
            sev = 2
        spec = PARAMS[k]
        exempt = st["context"] in ("exercise", "recovery") and k in EXERCISE_EXEMPT
        # Absolute (population) limits are a safety net; their severity is weighted by whether the
        # value is ALSO unusual for this person. A trained athlete's sleeping HR of 40 or RR of 8
        # is below generic limits but normal for them -> observation (L1), never silently ignored.
        corroborated = zb >= self.cfg.z_corroborate
        self._corroborated[k] = corroborated
        if not exempt:
            if (spec.hard_low is not None and v < spec.hard_low) or (spec.hard_high is not None and v > spec.hard_high):
                sev = max(sev, 2 if corroborated else 1)
        lo, hi = CRITICAL.get(k, (None, None))
        crit = (lo is not None and v < lo) or (hi is not None and v > hi)
        if crit and not (exempt and k == "hr" and v < 190):
            sev = 3 if zb >= self.cfg.z_mild else 2
        return sev

    def _intermittent(self, k: str, st: dict, sev: int, repeat: list[str]) -> int:
        """Persistence for spot-check channels (BP cuff) counts MEASUREMENTS, not minutes.

        A held cuff value is one observation, however long it is displayed. Standard practice
        is to repeat an abnormal cuff reading before acting on it, so: one abnormal reading
        -> observation + 'repeat measurement' request; two consecutive abnormal readings
        confirm the severity. A single critical reading is capped at level 2 until repeated.
        """
        fresh = st["age_min"].get(k) == 0
        if fresh:
            self._meas[k] = self._meas[k] + 1 if sev >= 1 else 0
            self._meas_sev[k] = (self._meas_sev[k] + [sev])[-2:] if sev >= 1 else []
            for s in (1, 2, 3):   # minutes counter kept only for reporting
                self.counts[k][s] = 0
        for s in (1, 2, 3):
            self.counts[k][s] = self.counts[k][s] + 1 if sev >= s else 0
        n = self._meas[k]
        if n == 0:
            return 0
        if n == 1:
            last = self._meas_sev[k][-1]
            if last >= 2:
                repeat.append(f"repeat {PARAMS[k].label} measurement now")
            return {1: 0, 2: 1, 3: 2}[last]
        return min(self._meas_sev[k])   # confirmed by two consecutive readings

    def _projected_crossing(self, k: str, st: dict, horizon_min: float = 60.0) -> bool:
        spec, v = PARAMS[k], st["values"].get(k)
        sl, sd = st["slope_h"][k], st["slope_sd_h"][k]
        if v is None or sd <= 0 or abs(sl) < 3 * sd:
            return False
        if sl < 0 and spec.hard_low is not None and spec.bad_direction in (-1, 0):
            return v + sl * horizon_min / 60 < spec.hard_low
        if sl > 0 and spec.hard_high is not None and spec.bad_direction in (1, 0):
            return v + sl * horizon_min / 60 > spec.hard_high
        return False

    # ------------------------------------------------------------------
    def classify(self, st: dict, anomaly: float | None = None, risk: float | None = None,
                 patterns: list[dict] | None = None) -> Classification:
        cfg = self.cfg
        reasons: list[str] = []
        pinfo: dict = {}
        verify: list[str] = []
        repeat: list[str] = []
        sustained: dict[str, int] = {}
        for k in VITAL_KEYS:
            q = st["quality"][k]
            sev = self._severity(k, st)   # 0 for channels that failed quality gating
            if k in INTERMITTENT:
                ss = self._intermittent(k, st, sev, repeat)
            else:
                for s in (1, 2, 3):
                    self.counts[k][s] = self.counts[k][s] + 1 if sev >= s else 0
                need = {1: cfg.mild_persist_min, 2: cfg.moderate_persist_min, 3: cfg.severe_persist_min}
                ss = max([s for s in (1, 2, 3) if self.counts[k][s] >= need[s]] + [0])
                # a moderate value already persisting longer than the mild window counts as at least mild
                if ss == 0 and self.counts[k][1] >= cfg.mild_persist_min:
                    ss = 1
            sustained[k] = ss
            if sev or ss:
                pinfo[k] = {"sev": sev, "sustained_sev": ss, "z": st["z"].get(k), "value": st["values"].get(k),
                            "expected": st["expected"][k], "unit": PARAMS[k].unit,
                            "sustained_min": self.counts[k][max(sev, 1)], "quality": q}
        # faulted channels never escalate medically; they raise a 'verify reading' observation
        faulted = set()
        for f in st["faults"]:
            ch = {"ecg": "hr"}.get(f.split(":")[0], f.split(":")[0])
            if ch in VITAL_KEYS and f.endswith(("flatline", "implausible", "lead_off")):
                faulted.add(ch)
        for ch in VITAL_KEYS:   # a sensor alert needs the fault to persist (one glitchy minute is not an event)
            self._fault_min[ch] = self._fault_min[ch] + 1 if ch in faulted else 0
            if self._fault_min[ch] >= cfg.fault_persist_min:
                verify.append(ch)

        # Multi-system escalation counts only deviations that are unusual FOR THIS PERSON
        # (z-corroborated). Two uncorroborated observations do not make an emergency.
        personal = {k: s for k, s in sustained.items() if s >= 1 and self._corroborated.get(k)}
        systems_1 = sorted({PARAMS[k].system for k, s in personal.items() if s >= 1})
        systems_2 = sorted({PARAMS[k].system for k, s in personal.items() if s >= 2})
        deteriorating = [k for k in VITAL_KEYS if sustained[k] >= 1 and self._projected_crossing(k, st)]

        cand = max(sustained.values())
        for k, s in sustained.items():
            if s:
                z = st["z"][k]
                reasons.append(f"{PARAMS[k].label} {st['values'][k]:.1f} {PARAMS[k].unit} vs personal expected "
                               f"{st['expected'][k]:.1f} (z={z:+.1f}) sustained {pinfo[k]['sustained_min']} min")
        if len(systems_1) >= 2:
            cand = max(cand, 2)
            reasons.append(f"Multiple physiological systems deviating: {', '.join(systems_1)}")
        if len(systems_2) >= 2:
            cand = max(cand, 3)
            reasons.append(f"Moderate/severe deviation in >=2 systems: {', '.join(systems_2)}")
        if deteriorating:
            cand = max(cand, min(cand + 1, 3) if cand >= 2 else 2)
            reasons.append("Projected to cross an absolute limit within 60 min: " + ", ".join(deteriorating))
        if patterns and cand >= 1:
            reasons.append("Co-deviation pattern: " + "; ".join(p["name"] for p in patterns))
        if cand == 0:
            if risk is not None and risk >= cfg.forecast_watch:
                cand = 1
                reasons.append(f"Risk forecaster score {risk:.2f} >= watch threshold (simulation-trained)")
            if anomaly is not None and anomaly >= 0.997 and sum(1 for k in VITAL_KEYS if self.counts[k][1] >= 3) >= 1:
                cand = 1
                reasons.append(f"Multivariate anomaly score {anomaly:.3f} (unusual vs nominal operation)")
        if repeat:
            reasons.append("Single spot-check reading - confirm before acting: " + ", ".join(repeat))
        sensor_alert = bool(verify)
        if sensor_alert and cand == 0:
            cand = 1
            reasons.append("Sensor reliability issue - verify readings: " + ", ".join(sorted(set(verify))))

        # hysteresis: escalate immediately, de-escalate only after the lower level holds
        if cand >= self.level:
            self.level = cand
            self._lower_since = 0
        else:
            self._lower_since += 1
            if self._lower_since >= cfg.clear_hold_min:
                self.level = cand
                self._lower_since = 0
        if self.level > cand:
            reasons.append(f"Holding level {self.level} (hysteresis {self._lower_since}/{cfg.clear_hold_min} min)")

        conf = self._confidence(st, pinfo, systems_1, anomaly, risk)
        return Classification(self.level, LEVEL_LABELS[self.level], cand, reasons, pinfo, systems_1, deteriorating,
                              conf, "high" if conf >= 0.75 else "medium" if conf >= 0.5 else "low",
                              sensor_alert, sorted(set(verify)) + repeat)

    def _confidence(self, st, pinfo, systems, anomaly, risk) -> float:
        if not pinfo:
            qs = [st["quality"][k] for k in ("hr", "spo2", "rr", "temp")]
            return round(float(sum(qs) / len(qs)), 2)
        q = sum(p["quality"] for p in pinfo.values()) / len(pinfo)
        unc = sum(st["uncertainty"][k] for k in pinfo) / len(pinfo)
        corroboration = min(1.0, 0.5 + 0.25 * (len(systems) - 1) + 0.1 * (len(pinfo) - 1))
        model = 0.5 if anomaly is None else min(1.0, 0.5 + anomaly / 2)
        c = q * (1 - min(unc * 3, 0.5)) * (0.6 * corroboration + 0.4 * model)
        return round(float(max(0.05, min(c, 0.99))), 2)
