"""Explainable emergency report generation (structured, template-based)."""

from __future__ import annotations

from ares.config import PARAMS

EARTH_PRIORITY = {0: "P4 routine", 1: "P3 next window", 2: "P2 priority", 3: "P1 immediate"}
CREW_NOTIFY = {0: "none", 1: "Affected crew member + CMO (display)", 2: "CMO + Commander (alarm)",
               3: "ALL CREW (master alarm)"}

CATEGORY_TITLES = {
    "hypoxaemia": "OXYGEN SATURATION ABNORMALITY", "febrile": "THERMAL + CARDIOVASCULAR ABNORMALITY",
    "hypovolaemia": "CARDIOVASCULAR / FLUID ABNORMALITY", "arrhythmia": "CARDIAC RHYTHM ABNORMALITY",
    "respiratory": "RESPIRATORY ABNORMALITY", "fatigue": "SLEEP / FATIGUE ACCUMULATION",
    "spe": "RADIATION ENVIRONMENT EVENT", "sensor_fault": "SENSOR RELIABILITY EVENT",
    "multi_system": "MULTI-PARAMETER PHYSIOLOGICAL ABNORMALITY",
}


def categorise(cls: dict, patterns: list[dict]) -> list[str]:
    """Pattern categories take precedence; single-parameter categories only when no pattern explains it."""
    cats = [p["id"] for p in patterns]
    if len(cls["systems"]) >= 2:
        cats.append("multi_system")
    if not patterns:
        for k, info in cls["params"].items():
            if info["sustained_sev"] >= 1:
                cats.append(k)
    if cls["sensor_alert"] and not cats:
        cats.append("sensor_fault")
    return list(dict.fromkeys(cats)) or ["any"]


def build_report(*, astronaut: dict, t: float, cls: dict, patterns: list[dict], state: dict,
                 categories: list[str], protocols: list[dict], explanation: dict, mission: dict,
                 anomaly: float | None, risk: float | None, news2: dict | None) -> dict:
    lvl = cls["level"]
    primary = next((c for c in categories if c in CATEGORY_TITLES), "multi_system")
    title = CATEGORY_TITLES.get(primary, "PHYSIOLOGICAL ABNORMALITY")
    if len([c for c in categories if c in CATEGORY_TITLES]) > 1 or len(cls["systems"]) >= 2:
        title = "MULTI-PARAMETER PHYSIOLOGICAL ABNORMALITY" if primary not in ("spe", "sensor_fault") else title
    measurements = []
    for k, info in cls["params"].items():
        if info["value"] is None:
            continue
        lo, hi = state["band"][k]
        measurements.append({
            "parameter": PARAMS[k].label, "value": round(info["value"], 1), "unit": PARAMS[k].unit,
            "personal_expected": round(info["expected"], 1), "personal_band_2sd": [round(lo, 1), round(hi, 1)],
            "z": round(info["z"], 2) if info["z"] is not None else None,
            "sustained_min": info["sustained_min"], "signal_quality": round(info["quality"], 2),
            "source": "measured" if PARAMS[k].measured else "derived",
        })
    add_meas = []
    for p in protocols:
        add_meas += p.get("additional_measurements", [])
    add_meas += [f"Missing/unreliable: {m}" for m in explanation.get("missing", [])]
    owlt = mission["one_way_light_time_min"]
    return {
        "event": f"EVENT: {title}",
        "astronaut": {"id": astronaut["id"], "name": astronaut["name"], "role": astronaut["role"]},
        "mission_time_min": t,
        "level": lvl, "level_label": cls["label"],
        "abnormal_measurements": measurements,
        "baseline_comparison": explanation.get("baseline_text", []),
        "detection_confidence": {"score": cls["confidence"], "label": cls["confidence_label"]},
        "potential_risk_category": [p["name"] for p in patterns] or [title.title()],
        "reasons": cls["reasons"],
        "model_outputs": {
            "anomaly_score": None if anomaly is None else round(anomaly, 3),
            "risk_forecast_30min": None if risk is None else round(risk, 3),
            "risk_note": "Predictive score from a simulation-trained model - NOT a medically validated probability.",
            "news2": news2,
        },
        "additional_measurements_required": list(dict.fromkeys(add_meas)),
        "recommended_protocols": [{"id": p["id"], "title": p["title"], "steps": p["assessment_steps"],
                                   "escalation": p["escalation_criteria"], "source": p["source"],
                                   "approval": p["approval"]} for p in protocols],
        "crew_notification": CREW_NOTIFY[lvl],
        "earth_communication_priority": EARTH_PRIORITY[lvl],
        "mission_context": {
            "comm_mode": mission["comm_mode"], "one_way_delay_min": round(owlt, 1),
            "earliest_ground_response_min": None if mission["comm_mode"] == "blackout" else round(2 * owlt, 1),
            "guidance": ("Earth link unavailable - act on onboard protocols; report queued." if mission["comm_mode"] == "blackout"
                         else f"Ground cannot respond for at least {2 * owlt:.0f} min - begin onboard assessment now."),
        },
        "disclaimer": "Decision support only. Protocols are UNAPPROVED DEMO entries. Final decisions rest with the CMO/flight surgeon.",
    }
