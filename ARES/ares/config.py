"""Central configuration and reference values.

Every number here is either (a) a published reference value with a source,
or (b) an ENGINEERING CHOICE for this prototype, labelled as such.
Engineering choices are NOT clinical thresholds; in a real system they
would be set and signed off by flight surgeons.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Physical constants / mission geometry
# ---------------------------------------------------------------------------
AU_KM = 149_597_870.7
SPEED_OF_LIGHT_KM_S = 299_792.458
SUN_GM_KM3_S2 = 1.32712440018e11
EARTH_ORBIT_AU = 1.000
MARS_ORBIT_AU = 1.524  # mean semi-major axis; circular-coplanar approximation

# ---------------------------------------------------------------------------
# Radiation reference values (published)
# ---------------------------------------------------------------------------
# Zeitlin et al., Science 340 (2013): MSL/RAD measured an average GCR dose
# equivalent rate of ~1.84 mSv/day inside the cruise vehicle.
GCR_CRUISE_MSV_PER_DAY = 1.84
# Hassler et al., Science 343 (2014): ~0.64 mSv/day on the Martian surface.
GCR_MARS_SURFACE_MSV_PER_DAY = 0.64
# NASA-STD-3001 Vol 1 [V1 4030]: career effective dose < 600 mSv.
NASA_CAREER_LIMIT_MSV = 600.0
# NASA-STD-3001 Vol 1 [V1 4031]: design-reference SPE < 250 mSv effective dose.
NASA_SPE_LIMIT_MSV = 250.0
# ENGINEERING CHOICE: assumed storm-shelter attenuation of SPE dose.
STORM_SHELTER_SPE_FACTOR = 0.3

# ---------------------------------------------------------------------------
# Physiological parameters
# ---------------------------------------------------------------------------
# Population priors used ONLY to initialise each astronaut's personal
# Bayesian baseline before individual data exist (healthy adult at rest).
# "hard" limits are commonly used clinical reference points for
# "act now" values; they are placeholders pending flight-surgeon review.


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    unit: str
    system: str            # physiological system for multi-system counting
    prior_mean: float
    prior_sd: float
    bad_direction: int     # +1 high is bad, -1 low is bad, 0 both
    hard_low: float | None
    hard_high: float | None
    plausible: tuple[float, float]  # physically plausible sensor range
    measured: bool = True  # False -> derived estimate
    sensor: str = ""


PARAMS: dict[str, ParamSpec] = {
    p.key: p
    for p in [
        ParamSpec("hr", "Heart rate", "bpm", "cardiovascular", 68, 9, 0, 40, 140,
                  (25, 230), measured=False, sensor="ECG (derived from R-R intervals)"),
        ParamSpec("hrv_rmssd", "HRV (RMSSD)", "ms", "autonomic", 42, 15, 0, None, None,
                  (1, 300), measured=False, sensor="ECG (derived)"),
        ParamSpec("spo2", "SpO2", "%", "respiratory", 97.5, 1.2, -1, 88, None,
                  (50, 100.5), sensor="Pulse oximeter"),
        ParamSpec("rr", "Respiratory rate", "br/min", "respiratory", 14, 2.2, 0, 8, 28,
                  (3, 60), sensor="Respiratory belt / impedance"),
        ParamSpec("sbp", "Systolic BP", "mmHg", "cardiovascular", 118, 9, 0, 85, 170,
                  (50, 250), sensor="BP cuff (intermittent)"),
        ParamSpec("dbp", "Diastolic BP", "mmHg", "cardiovascular", 76, 7, 0, 45, 105,
                  (30, 150), sensor="BP cuff (intermittent)"),
        ParamSpec("temp", "Core temp (est.)", "degC", "thermal", 36.9, 0.25, 0, 35.5, 38.5,
                  (32, 43), sensor="Skin/core temperature patch"),
    ]
}

VITAL_KEYS = list(PARAMS.keys())

# ---------------------------------------------------------------------------
# Detection / classification engineering choices
# ---------------------------------------------------------------------------


@dataclass
class DetectionConfig:
    # z-score bands relative to the PERSONAL context-conditioned baseline
    z_mild: float = 3.0
    z_moderate: float = 4.5
    # an absolute-limit breach counts fully only if also >= this personal z (else observation)
    z_corroborate: float = 2.0
    # minutes a sensor fault must persist before a 'verify sensor' observation is raised
    fault_persist_min: int = 3
    # persistence requirements (minutes of mission time; 1 sample/min)
    mild_persist_min: int = 10
    moderate_persist_min: int = 5
    severe_persist_min: int = 2
    # de-escalation hysteresis (minutes a lower level must hold)
    clear_hold_min: int = 15
    # signal quality below this -> reading not trusted for escalation
    min_quality: float = 0.6
    # forecast risk that upgrades L0->L1 (observation)
    forecast_watch: float = 0.5
    # baseline learning
    baseline_half_life_days: float = 7.0
    baseline_gate_z: float = 2.5   # samples beyond this do NOT update baseline
    warmup_samples: int = 60


DETECTION = DetectionConfig()


@dataclass
class SimConfig:
    seed: int = 7
    sample_period_min: float = 1.0       # vital-sign stream: 1 sample / minute
    ecg_fs: int = 250                    # synthetic ECG sampling rate (Hz)
    ecg_window_s: float = 10.0
    crew_size: int = 4
    transfer_days: float = 259.0          # Hohmann Earth->Mars (computed in mission.context)
    extra: dict = field(default_factory=dict)


SIM = SimConfig()

DISCLAIMER = (
    "ARES is a research prototype for a hackathon. It is NOT a medical device, "
    "is NOT clinically validated, and all crew physiological streams shown in the "
    "demo are SIMULATED."
)
