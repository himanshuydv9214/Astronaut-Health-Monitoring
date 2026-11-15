"""Fictional astronaut profiles for the SIMULATED crew.

These are invented people. Baseline values are plausible healthy-adult
resting values chosen for demonstration, not taken from any real astronaut.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AstronautProfile:
    id: str
    name: str
    role: str
    age: int
    # resting, awake baselines
    hr: float
    hrv_rmssd: float
    spo2: float
    rr: float
    sbp: float
    dbp: float
    temp: float
    # schedule offsets (minutes) so crew are not perfectly synchronised
    sleep_start_min: int = 22 * 60
    sleep_hours: float = 8.0
    exercise_slots: tuple[int, ...] = (9 * 60, 16 * 60)
    exercise_min: int = 60
    prior_career_dose_msv: float = 0.0
    notes: str = ""
    medical_history: list[str] = field(default_factory=list)


DEFAULT_CREW: list[AstronautProfile] = [
    AstronautProfile("AST-1", "A. Reyes", "Commander", 46, hr=62, hrv_rmssd=38, spo2=97.8,
                     rr=13, sbp=121, dbp=78, temp=36.8, sleep_start_min=22 * 60,
                     prior_career_dose_msv=118.0, notes="Two prior ISS increments (fictional).",
                     medical_history=["No significant history (fictional)"]),
    AstronautProfile("AST-2", "K. Tanaka", "Pilot", 39, hr=58, hrv_rmssd=55, spo2=98.1,
                     rr=12, sbp=114, dbp=72, temp=36.7, sleep_start_min=22 * 60 + 30,
                     exercise_slots=(10 * 60, 17 * 60), prior_career_dose_msv=46.0,
                     medical_history=["Seasonal allergies (fictional)"]),
    AstronautProfile("AST-3", "L. Okafor", "Flight Engineer / CMO", 42, hr=70, hrv_rmssd=34,
                     spo2=97.2, rr=15, sbp=124, dbp=80, temp=37.0, sleep_start_min=21 * 60 + 30,
                     exercise_slots=(8 * 60, 15 * 60), prior_career_dose_msv=72.0,
                     notes="Crew Medical Officer.",
                     medical_history=["No significant history (fictional)"]),
    AstronautProfile("AST-4", "S. Novak", "Mission Specialist", 35, hr=66, hrv_rmssd=47,
                     spo2=97.6, rr=14, sbp=112, dbp=70, temp=36.9, sleep_start_min=23 * 60,
                     exercise_slots=(11 * 60, 18 * 60), prior_career_dose_msv=0.0,
                     notes="First flight (fictional).",
                     medical_history=["No significant history (fictional)"]),
]


def get_crew() -> list[AstronautProfile]:
    # return copies so simulations cannot mutate the module-level defaults
    from copy import deepcopy

    return deepcopy(DEFAULT_CREW)


def random_profile(index: int, seed: int = 0) -> AstronautProfile:
    """A random FICTIONAL astronaut for the evaluation population.

    Between-person spread is roughly that of healthy adults at rest (illustrative
    values, not fitted to any dataset). Used to build an astronaut-level
    train/test split: models are always evaluated on people they never saw.
    """
    import numpy as np

    rng = np.random.default_rng(10_000 + 97 * index + seed)
    fit = rng.uniform(0, 1)  # fitter people: lower resting HR, higher HRV
    return AstronautProfile(
        id=f"SYN-{index:03d}", name=f"Synthetic {index:03d}", role="Synthetic evaluation subject",
        age=int(rng.integers(30, 55)),
        hr=float(np.clip(rng.normal(70 - 14 * fit, 5), 48, 85)),
        hrv_rmssd=float(np.clip(rng.normal(30 + 30 * fit, 8), 15, 90)),
        spo2=float(np.clip(rng.normal(97.6, 0.5), 96.0, 99.0)),
        rr=float(np.clip(rng.normal(14.5, 1.5), 12, 18)),
        sbp=float(np.clip(rng.normal(118, 8), 100, 138)),
        dbp=float(np.clip(rng.normal(76, 6), 62, 88)),
        temp=float(np.clip(rng.normal(36.8, 0.2), 36.3, 37.3)),
        sleep_start_min=int(rng.integers(21 * 60, 23 * 60 + 30)),
        sleep_hours=float(rng.uniform(7.0, 8.5)),
        exercise_slots=(int(rng.integers(7 * 60, 11 * 60)), int(rng.integers(14 * 60, 18 * 60))),
        prior_career_dose_msv=float(rng.choice([0.0, rng.uniform(20, 150)])),
        notes="Randomly generated evaluation subject (fictional).",
    )
