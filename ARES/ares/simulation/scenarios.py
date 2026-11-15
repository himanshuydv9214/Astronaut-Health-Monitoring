"""Scenario library: physiological / environmental / sensor perturbations.

Each scenario is a set of `Effect`s. An Effect has a time envelope
(onset ramp, plateau, recovery ramp) and per-signal deltas. The scenario
designer also defines GROUND-TRUTH labels (level as a function of how
strongly the effect is expressed). Evaluation measures whether ARES
recovers the designer's labels - it does NOT measure clinical validity.

Magnitudes are illustrative, chosen to resemble textbook presentations;
they are not derived from astronaut data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Effect:
    start_min: float
    onset_min: float
    plateau_min: float | None          # None -> stays on until scenario cleared
    recovery_min: float
    deltas: dict[str, float]           # additive deltas on true physiology
    levels: list[tuple[float, int]] = field(default_factory=list)  # (envelope>=x -> level)
    event: str = ""
    # special channels
    sensor_fault: str | None = None    # 'spo2_flatline' | 'spo2_dropout' | 'ecg_leadoff'
    irregular_rhythm: float = 0.0      # 0..1 R-R irregularity (AF-like)
    sleep_reduction_h: float = 0.0
    spe_dose_msv_per_day: float = 0.0  # added dose-equivalent rate at plateau
    crew_wide: bool = False
    behavioral_strain: float = 0.0     # 0..1 psychological strain (drives simulated PVT/check-ins)
    co2_extra_mmhg: float = 0.0        # added cabin ppCO2 at plateau (CO2-removal degradation)

    def envelope(self, t: float) -> float:
        dt = t - self.start_min
        if dt < 0:
            return 0.0
        if dt < self.onset_min:
            return dt / max(self.onset_min, 1e-9)
        if self.plateau_min is None:
            return 1.0
        dt -= self.onset_min
        if dt < self.plateau_min:
            return 1.0
        dt -= self.plateau_min
        if dt < self.recovery_min:
            return 1.0 - dt / max(self.recovery_min, 1e-9)
        return 0.0

    def level_at(self, t: float) -> int:
        env = self.envelope(t)
        lvl = 0
        for thr, lv in self.levels:
            if env >= thr:
                lvl = max(lvl, lv)
        return lvl

    def end_min(self) -> float:
        if self.plateau_min is None:
            return float("inf")
        return self.start_min + self.onset_min + self.plateau_min + self.recovery_min


@dataclass
class Scenario:
    key: str
    name: str
    description: str
    effects: list[Effect]
    force_blackout: bool = False


def _sc(key, name, desc, effects, force_blackout=False):
    return Scenario(key, name, desc, effects, force_blackout)


def build_scenario(key: str, t0: float = 0.0) -> Scenario:
    """Instantiate a scenario starting at mission minute t0."""
    E = Effect
    lib = {
        "normal": lambda: _sc("normal", "Normal mission operation",
                              "No perturbation; nominal circadian, sleep and exercise cycles.", []),
        "gradual_deterioration": lambda: _sc(
            "gradual_deterioration", "Gradual physiological deterioration",
            "Slow multi-hour drift resembling a developing febrile illness: temperature, HR and RR rise, SpO2 sags.",
            [E(t0, 360, None, 120, {"temp": 1.6, "hr": 24, "rr": 7, "spo2": -3.0, "hrv_rmssd": -14},
               [(0.35, 1), (0.75, 2)], "gradual_deterioration")]),
        "spo2_drop": lambda: _sc(
            "spo2_drop", "Sudden oxygen saturation abnormality",
            "Rapid SpO2 fall over minutes with compensatory tachycardia and tachypnoea.",
            [E(t0, 6, None, 30, {"spo2": -12.0, "hr": 22, "rr": 9},
               [(0.3, 2), (0.7, 3)], "hypoxaemia")]),
        "cardiac_arrhythmia": lambda: _sc(
            "cardiac_arrhythmia", "Abnormal cardiovascular pattern",
            "Onset of an irregular, fast rhythm (AF-like R-R irregularity) with BP drop.",
            [E(t0, 3, None, 20, {"hr": 48, "sbp": -16, "dbp": -8},
               [(0.4, 2), (0.85, 3)], "arrhythmia", irregular_rhythm=0.9)]),
        "respiratory": lambda: _sc(
            "respiratory", "Respiratory abnormality",
            "Elevated respiratory rate with mild desaturation (e.g., CO2/air-quality or airway issue).",
            [E(t0, 30, None, 60, {"rr": 13, "spo2": -4.0, "hr": 12},
               [(0.4, 1), (0.8, 2)], "respiratory")]),
        "sleep_deprivation": lambda: _sc(
            "sleep_deprivation", "Sleep deprivation & fatigue accumulation",
            "Sleep opportunity shortened by 3.5 h/night; resting HR creeps up and HRV falls.",
            [E(t0, 3 * 1440, None, 1440, {"hr": 7, "hrv_rmssd": -16, "sbp": 5},
               [(0.5, 1)], "fatigue", sleep_reduction_h=3.5)]),
        "dehydration": lambda: _sc(
            "dehydration", "Dehydration-related abnormality",
            "Fluid deficit: tachycardia, falling BP, slight temperature rise.",
            [E(t0, 240, None, 180, {"hr": 22, "sbp": -20, "dbp": -10, "temp": 0.5, "hrv_rmssd": -10},
               [(0.4, 1), (0.8, 2)], "dehydration")]),
        "sensor_malfunction": lambda: _sc(
            "sensor_malfunction", "Sensor malfunction",
            "Pulse oximeter flatlines then drops out; ECG lead-off noise. Physiology is actually normal.",
            [E(t0, 1, 90, 1, {}, [], "sensor_fault", sensor_fault="spo2_flatline"),
             E(t0 + 95, 1, 60, 1, {}, [], "sensor_fault", sensor_fault="ecg_leadoff")]),
        "multi_system": lambda: _sc(
            "multi_system", "Multiple simultaneous abnormalities",
            "Concurrent thermal, respiratory and cardiovascular deviation (pneumonia-like pattern).",
            [E(t0, 90, None, 120, {"temp": 1.9, "rr": 10, "spo2": -6.0, "hr": 30, "sbp": -12,
                                   "hrv_rmssd": -18},
               [(0.3, 1), (0.6, 2), (0.9, 3)], "multi_system")]),
        "blackout_emergency": lambda: _sc(
            "blackout_emergency", "Communication blackout during a medical emergency",
            "SpO2 emergency while the Earth link is unavailable - ARES must operate autonomously.",
            [E(t0, 6, None, 30, {"spo2": -12.0, "hr": 22, "rr": 9},
               [(0.3, 2), (0.7, 3)], "hypoxaemia")], force_blackout=True),
        "radiation_event": lambda: _sc(
            "radiation_event", "Radiation exposure event (SPE)",
            "Solar particle event raises the dose-equivalent rate for ~12 h. Acute physiology is unchanged; "
            "the risk is cumulative dose, so the response is environmental (shelter), not clinical.",
            [E(t0, 60, 600, 120, {}, [(0.2, 2)], "spe", spe_dose_msv_per_day=100.0, crew_wide=True)]),
        "behavioral_strain": lambda: _sc(
            "behavioral_strain", "Isolation & workload strain (behavioral)",
            "Weeks into cruise: rising workload and isolation stress. Sleep shortens ~1 h, vigilance and mood "
            "decline over days; physiology shows only mild autonomic strain. Tests the behavioral channel.",
            [E(t0, 2 * 1440, None, 1440, {"hr": 4, "hrv_rmssd": -6}, [(0.5, 1)], "behavioral_strain",
               sleep_reduction_h=1.0, behavioral_strain=0.8)]),
        "co2_buildup": lambda: _sc(
            "co2_buildup", "Cabin CO2 build-up (life-support degradation)",
            "CO2 removal degrades: cabin ppCO2 climbs from ~2 to ~7 mmHg over ~2 h. All crew breathe a little "
            "faster and some report headaches. Tests ENVIRONMENTAL attribution instead of 4 separate illnesses.",
            [E(t0, 120, None, 90, {"rr": 3.5, "hr": 3}, [(0.5, 1)], "co2", co2_extra_mmhg=5.0, crew_wide=True)]),
        "gradual_cardiovascular": lambda: _sc(
            "gradual_cardiovascular", "Gradual cardiovascular changes",
            "Over ~8 hours resting heart rate creeps up, heart rate variability falls and blood pressure sags - "
            "the slow pattern of cardiovascular deconditioning or fluid shift. Tests drift detection, not alarms.",
            [E(t0, 480, None, 240, {"hr": 16, "hrv_rmssd": -14, "sbp": -10, "dbp": -5},
               [(0.8, 1)], "cardiovascular_drift")]),
        "recovery": lambda: _sc(
            "recovery", "Recovery & post-emergency monitoring",
            "Moderate hypoxaemic episode that resolves; tests de-escalation hysteresis and follow-up.",
            [E(t0, 5, 40, 90, {"spo2": -8.0, "hr": 18, "rr": 6},
               [(0.4, 2)], "hypoxaemia_resolving")]),
    }
    if key not in lib:
        raise KeyError(f"Unknown scenario '{key}'. Options: {sorted(lib)}")
    return lib[key]()


SCENARIO_KEYS = [
    "normal", "gradual_deterioration", "spo2_drop", "cardiac_arrhythmia", "respiratory",
    "sleep_deprivation", "dehydration", "sensor_malfunction", "multi_system",
    "blackout_emergency", "radiation_event", "recovery",
]

# The 12 physiological/environmental scenarios above are used for model training and evaluation;
# the behavioral and cabin-CO2 scenarios are dashboard demonstrations (evaluated by their own modules).
UI_SCENARIO_KEYS = SCENARIO_KEYS + ["behavioral_strain", "co2_buildup", "gradual_cardiovascular"]
