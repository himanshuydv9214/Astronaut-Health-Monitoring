"""Radiation exposure intelligence.

Three quantities are kept strictly separate:

  MEASURED  - integrated personal dosimeter readings (in the demo the
              dosimeter itself is simulated, and labelled so).
  MODELLED  - expected GCR dose from published MSL/RAD mean rates for the
              current mission phase. Measured >> modelled flags an SPE.
  INFERRED BIOLOGICAL RISK - deliberately NOT computed. Individual cancer
              risk needs validated risk models (e.g., NASA's space cancer
              risk model), tissue-weighted effective dose and individual
              factors; short-term dosimetry cannot predict it. ARES reports
              dose against NASA-STD-3001 limits only.
"""

from __future__ import annotations

from ares.config import NASA_CAREER_LIMIT_MSV, NASA_SPE_LIMIT_MSV

SPE_RATIO = 3.0        # measured/modelled ratio that indicates an SPE (engineering choice)
SPE_PERSIST_MIN = 5


class DoseTracker:
    def __init__(self, prior_career_msv: float):
        self.prior = prior_career_msv
        self.mission_measured = 0.0
        self.mission_modelled = 0.0
        self.event_dose = 0.0
        self.max_event_dose = 0.0
        self.last_rate = 0.0

    def update(self, measured_rate_day: float, modelled_rate_day: float, dt_min: float, spe_active: bool) -> None:
        d = measured_rate_day * dt_min / 1440.0
        self.mission_measured += d
        self.mission_modelled += modelled_rate_day * dt_min / 1440.0
        self.last_rate = measured_rate_day
        if spe_active:
            self.event_dose += max(0.0, measured_rate_day - modelled_rate_day) * dt_min / 1440.0
            self.max_event_dose = max(self.max_event_dose, self.event_dose)
        else:
            self.event_dose = 0.0

    def snapshot(self, days_remaining: float, modelled_rate_day: float) -> dict:
        career = self.prior + self.mission_measured
        projected = career + modelled_rate_day * max(days_remaining, 0.0)
        return {
            "measured_mission_msv": round(self.mission_measured, 2),
            "modelled_mission_msv": round(self.mission_modelled, 2),
            "prior_career_msv": round(self.prior, 1),
            "career_total_msv": round(career, 1),
            "career_limit_msv": NASA_CAREER_LIMIT_MSV,
            "pct_career_limit": round(100 * career / NASA_CAREER_LIMIT_MSV, 1),
            "projected_at_mars_arrival_msv": round(projected, 1),
            "current_event_msv": round(self.event_dose, 2),
            "spe_limit_msv": NASA_SPE_LIMIT_MSV,
            "dose_rate_msv_day": round(self.last_rate, 2),
            "inferred_biological_risk": "NOT COMPUTED - requires validated risk models; see docs/LIMITATIONS.md",
            "labels": {"measured": "simulated dosimeter", "modelled": "MSL/RAD published mean rates"},
        }


class SPEDetector:
    def __init__(self):
        self.count = 0
        self.active = False

    def update(self, crew_mean_rate: float, modelled_rate: float) -> bool:
        if crew_mean_rate > SPE_RATIO * modelled_rate:
            self.count += 1
        else:
            self.count = max(0, self.count - 1)
        if not self.active and self.count >= SPE_PERSIST_MIN:
            self.active = True
        if self.active and self.count == 0:
            self.active = False
        return self.active
