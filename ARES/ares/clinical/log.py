"""Symptom reports and laboratory results (immune & clinical context).

From the team's immune-health research: most immune markers (blood counts,
cytokines, viral reactivation) need laboratory analysis and CANNOT be measured
continuously by wearables, and temperature/HR/sleep alone cannot establish an
immune problem. So ARES does not pretend to sense immunity. Instead it:

  * lets the crew log symptoms (fever/chills, rash, allergy symptoms, sore
    throat, headache, fatigue, cold sores ...) in seconds;
  * stores lab results whenever an onboard analyser or sample is available,
    compared with the astronaut's OWN pre-flight values (not population ranges);
  * uses symptoms as corroborating evidence for physiological patterns
    (e.g., reported fever + temperature above personal baseline), and headache
    reports as evidence for cabin-CO2 attribution.

Pre-flight lab values for the fictional crew are SIMULATED. Reference ranges
below are generic adult ranges for display only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SYMPTOMS = ["fever_chills", "headache", "rash", "allergy_symptoms", "sore_throat", "cough",
            "nasal_congestion", "fatigue", "cold_sore", "nausea", "dizziness", "eye_or_vision_change"]

# label, unit, generic adult range (display only)
LABS = {
    "wbc": ("White blood cells", "10^9/L", (4.0, 11.0)),
    "lymphocytes": ("Lymphocytes", "10^9/L", (1.0, 4.8)),
    "neutrophils": ("Neutrophils", "10^9/L", (1.8, 7.7)),
    "crp": ("C-reactive protein", "mg/L", (0.0, 5.0)),
    # comprehensive-metabolic-panel markers (as in the Inspiration4 CMP, OSD-575) -> organ panels
    "creatinine": ("Creatinine (kidney marker)", "mg/dL", (0.6, 1.3)),
    "bun": ("Blood urea nitrogen (kidney marker)", "mg/dL", (7.0, 20.0)),
    "alt": ("ALT (liver enzyme)", "U/L", (7.0, 56.0)),
    "ast": ("AST (liver enzyme)", "U/L", (10.0, 40.0)),
}
LAB_ORGAN = {"creatinine": "kidney", "bun": "kidney", "alt": "liver", "ast": "liver",
             "wbc": "systemic", "lymphocytes": "systemic", "neutrophils": "systemic", "crp": "systemic"}
PERSONAL_DEV_FLAG = 0.30    # >= 30 % change vs own pre-flight value (engineering choice)


@dataclass
class ClinicalLog:
    astronaut_id: str
    preflight_labs: dict = field(default_factory=dict)
    symptoms: list[dict] = field(default_factory=list)
    labs: list[dict] = field(default_factory=list)

    def report_symptoms(self, t: float, items: list[str], note_category: str | None = None) -> dict:
        items = [s for s in items if s in SYMPTOMS]
        rec = {"t": t, "symptoms": items}
        self.symptoms.append(rec)
        return rec

    def add_labs(self, t: float, values: dict) -> dict:
        rec = {"t": t, "values": {k: float(v) for k, v in values.items() if k in LABS}}
        self.labs.append(rec)
        return self.lab_assessment()

    def active_symptoms(self, now: float, window_min: float = 24 * 60) -> list[str]:
        out = []
        for r in self.symptoms:
            if now - r["t"] <= window_min:
                out += r["symptoms"]
        return sorted(set(out))

    def lab_assessment(self) -> dict:
        if not self.labs:
            return {"latest": None, "flags": []}
        last = self.labs[-1]
        flags = []
        self.flag_keys = []
        for k, v in last["values"].items():
            label, unit, (lo, hi) = LABS[k]
            base = self.preflight_labs.get(k)
            rel = (v - base) / base if base else None
            outside = not (lo <= v <= hi)
            if (rel is not None and abs(rel) >= PERSONAL_DEV_FLAG) or outside:
                self.flag_keys.append(k)
                flags.append(f"{label} {v:g} {unit}" + (f" ({rel:+.0%} vs own pre-flight {base:g})" if rel is not None else "")
                             + (" - outside generic range" if outside else ""))
        return {"latest": last, "flags": flags, "flag_keys": list(self.flag_keys), "preflight": self.preflight_labs,
                "note": "Lab changes need clinical interpretation; an abnormal marker is not a diagnosis."}

    def view(self, now: float) -> dict:
        return {"preflight": self.preflight_labs, "active_symptoms_24h": self.active_symptoms(now), "symptom_log": self.symptoms[-20:][::-1],
                "labs": self.lab_assessment(), "lab_history": self.labs[-10:], "symptom_options": SYMPTOMS,
                "lab_fields": {k: {"label": v[0], "unit": v[1], "range": v[2]} for k, v in LABS.items()}}
