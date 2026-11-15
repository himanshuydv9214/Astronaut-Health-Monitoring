"""Crew physiological stream simulator (ALL OUTPUT IS SIMULATED).

Model per astronaut, per signal, sampled once per mission minute:

    true(t) = personal_baseline + activity_offset(t) [first-order lag, tau=5 min]
              + circadian(t) + AR(1) noise + sum(scenario effects)

    reading(t) = true(t) + measurement noise + artefacts / sensor faults

Activity follows a daily schedule (sleep ~8 h, two exercise sessions;
ISS crews typically exercise about 2 h per day). Blood pressure is an
intermittent cuff measurement (every 15 min, NaN otherwise) to exercise
the missing-data path. The pulse oximeter also reports pulse rate, which
gives ARES a redundant heart-rate source for cross-checking the ECG.

Ground-truth labels (level, events, sensor faults) are emitted alongside
readings for evaluation only; the ARES pipeline never sees them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ares.config import GCR_CRUISE_MSV_PER_DAY, SIM, VITAL_KEYS
from ares.processing.ecg import process_ecg_window
from ares.simulation.ecg import synth_ecg
from ares.simulation.profiles import AstronautProfile
from ares.simulation.scenarios import Effect, Scenario

ACTIVITY_OFFSETS = {
    "sleep":    {"hr": -8, "hrv_rmssd": 12, "spo2": -0.4, "rr": -2.0, "sbp": -10, "dbp": -6, "temp": -0.30},
    "rest":     {k: 0.0 for k in VITAL_KEYS},
    "exercise": {"hr": 48, "hrv_rmssd": -24, "spo2": -0.6, "rr": 9.0, "sbp": 24, "dbp": 2, "temp": 0.55},
}
AR_PHI = 0.92
AR_SD = {"hr": 1.4, "hrv_rmssd": 3.5, "spo2": 0.18, "rr": 0.35, "sbp": 2.2, "dbp": 1.6, "temp": 0.025}
MEAS_SD = {"hr": 0.8, "hrv_rmssd": 3.0, "spo2": 0.35, "rr": 0.5, "sbp": 3.0, "dbp": 2.5, "temp": 0.04}
ACTIVITY_COUNTS = {"sleep": 0.03, "rest": 0.25, "exercise": 1.6}
BP_PERIOD_MIN = 15


@dataclass
class SimSample:
    t_min: float
    astronaut_id: str
    activity_counts: float
    readings: dict[str, float]          # what sensors report (may be NaN)
    device: dict[str, float]            # device-reported status (perfusion index, ECG contact)
    pulse_rate: float                   # oximeter pulse rate (redundant HR)
    dose_rate_msv_day: float            # dosimeter reading
    ecg: np.ndarray | None = None       # optional raw ECG window (live mode)
    ecg_proc: dict | None = None
    truth: dict = field(default_factory=dict)


class AstronautSimulator:
    def __init__(self, profile: AstronautProfile, seed: int = 0):
        self.p = profile
        self.rng = np.random.default_rng(seed)
        self.effects: list[Effect] = []
        self._ar = {k: 0.0 for k in VITAL_KEYS}
        self._lag = {k: 0.0 for k in VITAL_KEYS}
        self._stuck: dict[str, float] = {}
        self._last_bp = (np.nan, np.nan)

    # ------------------------------------------------------------------ schedule
    def sleep_reduction_h(self, t: float) -> float:
        return max([e.sleep_reduction_h * e.envelope(t) for e in self.effects] + [0.0])

    def activity_state(self, t: float) -> str:
        m = t % 1440
        red = self.sleep_reduction_h(t) * 60
        start = (self.p.sleep_start_min + red) % 1440
        dur = self.p.sleep_hours * 60 - red
        if (m - start) % 1440 < dur:
            return "sleep"
        for s in self.p.exercise_slots:
            if 0 <= m - s < self.p.exercise_min:
                return "exercise"
        return "rest"

    def _circadian(self, t: float) -> dict[str, float]:
        # body temperature minimum ~2 h before habitual wake, peak ~12 h later
        wake = (self.p.sleep_start_min + self.p.sleep_hours * 60) % 1440
        phase = 2 * math.pi * (((t % 1440) - (wake + 10 * 60)) / 1440.0)
        c = math.cos(phase)
        return {"hr": 3.0 * c, "temp": 0.25 * c, "sbp": 3.0 * c, "dbp": 2.0 * c, "rr": 0.5 * c,
                "hrv_rmssd": -4.0 * c, "spo2": 0.0}

    # ------------------------------------------------------------------ effects
    def add_scenario(self, sc: Scenario) -> None:
        self.effects.extend([e for e in sc.effects if not e.crew_wide])

    def clear(self) -> None:
        self.effects.clear()
        self._stuck.clear()

    # ------------------------------------------------------------------ step
    def step(self, t: float, crew_effects: list[Effect] | None = None, with_ecg: bool = False,
             base_dose_rate: float = GCR_CRUISE_MSV_PER_DAY, spe_attenuation: float = 1.0) -> SimSample:
        crew_effects = crew_effects or []
        effects = self.effects + crew_effects
        act = self.activity_state(t)
        circ = self._circadian(t)
        true: dict[str, float] = {}
        base = {"hr": self.p.hr, "hrv_rmssd": self.p.hrv_rmssd, "spo2": self.p.spo2, "rr": self.p.rr,
                "sbp": self.p.sbp, "dbp": self.p.dbp, "temp": self.p.temp}
        for k in VITAL_KEYS:
            target = ACTIVITY_OFFSETS[act].get(k, 0.0)
            self._lag[k] += (target - self._lag[k]) * (1 - math.exp(-SIM.sample_period_min / 5.0))
            self._ar[k] = AR_PHI * self._ar[k] + self.rng.normal(0, AR_SD[k])
            delta = sum(e.deltas.get(k, 0.0) * e.envelope(t) for e in effects)
            true[k] = base[k] + self._lag[k] + circ.get(k, 0.0) + self._ar[k] + delta
        true["spo2"] = min(true["spo2"], 100.0)
        true["hrv_rmssd"] = max(true["hrv_rmssd"], 4.0)
        irregular = max([e.irregular_rhythm * e.envelope(t) for e in effects] + [0.0])
        if irregular > 0.3:
            true["hrv_rmssd"] += 90 * irregular

        faults = {e.sensor_fault for e in effects if e.sensor_fault and e.envelope(t) > 0}
        readings = {k: true[k] + self.rng.normal(0, MEAS_SD[k]) for k in VITAL_KEYS}
        readings["hrv_rmssd"] = max(readings["hrv_rmssd"], 1.0)   # devices never report negative RMSSD
        device = {"spo2_perfusion": float(np.clip(self.rng.normal(3.0, 0.6), 0.2, 8)), "ecg_contact": 1.0}
        motion = 0.0
        if act == "exercise" and self.rng.random() < 0.08:  # motion artefact
            readings["spo2"] -= self.rng.uniform(3, 9)
            device["spo2_perfusion"] = float(self.rng.uniform(0.1, 0.5))
            motion = 1.0
        pulse_rate = true["hr"] + self.rng.normal(0, 1.5)

        # sensor faults
        if "spo2_flatline" in faults:
            self._stuck.setdefault("spo2", round(readings["spo2"]))
            readings["spo2"] = self._stuck["spo2"]
            pulse_rate = self._stuck.setdefault("pulse", round(pulse_rate))
        else:
            self._stuck.pop("spo2", None)
            self._stuck.pop("pulse", None)
        if "spo2_dropout" in faults:
            readings["spo2"] = np.nan
            pulse_rate = np.nan
        leadoff = "ecg_leadoff" in faults
        if leadoff:
            device["ecg_contact"] = 0.0

        # intermittent BP cuff
        if int(round(t)) % BP_PERIOD_MIN != 0:
            readings["sbp"] = np.nan
            readings["dbp"] = np.nan

        # quantisation like real devices
        if not np.isnan(readings["spo2"]):
            readings["spo2"] = float(min(100.0, round(readings["spo2"])))
        readings["temp"] = round(readings["temp"], 2)

        ecg = ecg_proc = None
        if with_ecg:
            ecg, _ = synth_ecg(true["hr"], max(true["hrv_rmssd"] - 90 * irregular, 4) if irregular > 0.3 else true["hrv_rmssd"],
                               SIM.ecg_window_s, SIM.ecg_fs, irregular, leadoff, motion, self.rng)
            ecg_proc = process_ecg_window(ecg, SIM.ecg_fs)
            readings["hr"] = ecg_proc["hr"] if ecg_proc["hr"] is not None else np.nan
            readings["hrv_rmssd"] = ecg_proc["hrv_rmssd"] if ecg_proc["hrv_rmssd"] is not None else np.nan
        elif leadoff:
            readings["hr"] = float(self.rng.uniform(30, 200))
            readings["hrv_rmssd"] = float(self.rng.uniform(100, 300))
        else:
            # Fast path (no ECG synthesis) reproduces the ECG pipeline's MEASURED estimation error so that
            # baselines, training data and the live ECG dashboard are statistically consistent:
            # HR ~1.7 % multiplicative; 10-s RMSSD lognormal, log-sd ~1.05/sqrt(beats-1), bias -5 %
            # (fitted by running synth_ecg -> process_ecg_window; see docs/DATA.md).
            nb = max(true["hr"] * SIM.ecg_window_s / 60.0, 3.0)
            readings["hr"] = float(true["hr"] * (1 + self.rng.normal(0, 0.017)))
            readings["hrv_rmssd"] = float(true["hrv_rmssd"] * np.exp(self.rng.normal(-0.05, 1.05 / np.sqrt(nb - 1))))

        spe = spe_attenuation * sum(e.spe_dose_msv_per_day * e.envelope(t) for e in effects)
        dose_rate = max(0.0, base_dose_rate + spe + self.rng.normal(0, 0.08))

        level = max([e.level_at(t) for e in effects] + [0])
        events = sorted({e.event for e in effects if e.level_at(t) > 0 or (e.sensor_fault and e.envelope(t) > 0)})
        truth = {"vitals": true, "level": level, "events": events, "sensor_faults": sorted(faults),
                 "activity": act, "irregular": irregular, "spe_rate": spe}
        return SimSample(t, self.p.id, float(ACTIVITY_COUNTS[act] * self.rng.lognormal(0, 0.25)),
                         readings, device, float(pulse_rate), float(dose_rate), ecg, ecg_proc, truth)


class CrewSimulator:
    """Holds one simulator per astronaut plus crew-wide (environmental) effects."""

    def __init__(self, profiles: list[AstronautProfile], seed: int = SIM.seed):
        self.sims = {p.id: AstronautSimulator(p, seed + i * 101) for i, p in enumerate(profiles)}
        self.profiles = {p.id: p for p in profiles}
        self.crew_effects: list[Effect] = []

    def apply(self, sc: Scenario, astronaut_id: str | None = None) -> None:
        crew = [e for e in sc.effects if e.crew_wide]
        self.crew_effects.extend(crew)
        if any(not e.crew_wide for e in sc.effects):
            targets = [astronaut_id] if astronaut_id else list(self.sims)[:1]
            for a in targets:
                self.sims[a].add_scenario(sc)

    def clear(self) -> None:
        self.crew_effects.clear()
        for s in self.sims.values():
            s.clear()

    def step(self, t: float, with_ecg: bool | set = False, base_dose_rate: float = GCR_CRUISE_MSV_PER_DAY,
             spe_attenuation: float = 1.0) -> dict[str, SimSample]:
        def ecg_for(aid):
            return aid in with_ecg if isinstance(with_ecg, set) else bool(with_ecg)
        return {aid: s.step(t, self.crew_effects, ecg_for(aid), base_dose_rate, spe_attenuation)
                for aid, s in self.sims.items()}
