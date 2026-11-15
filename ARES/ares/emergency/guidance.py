"""Four-part health guidance: What is happening / Immediate action / Possible long-term effects / Long-term care.

* "What is happening" is computed from live ARES data (measurements vs the astronaut's own baseline, onset, trend).
* "Immediate action" shows ONLY protocol steps stored in knowledge_base/protocols.json, verbatim, with source and
  approval status, plus operational decisions derived from the alert level (stop activity, notify CMO, Earth).
* "Long-term effects" and "Long-term care" come from knowledge_base/health_guidance.json; every effect carries an
  evidence label (NASA-recognised risk / spaceflight research / theoretical) and a source.
Nothing is generated; no treatment is ever proposed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ares.config import PARAMS
from ares.emergency.report import categorise

KB = Path(__file__).resolve().parents[2] / "knowledge_base" / "health_guidance.json"
_G = json.loads(KB.read_text(encoding="utf-8"))

PLAIN = {"hr": "Heart rate", "spo2": "Blood oxygen level (SpO₂)", "rr": "Breathing rate", "sbp": "Blood pressure (systolic)",
         "dbp": "Blood pressure (diastolic)", "temp": "Body temperature (estimated)", "hrv_rmssd": "Heart rate variability"}
CAT2CONCERN = {"hypoxaemia": "respiratory", "respiratory": "respiratory", "spo2": "respiratory", "rr": "respiratory",
               "arrhythmia": "cardio_rhythm", "hr": "cardio_rhythm", "hrv_rmssd": "cardio_drift",
               "sbp": "fluid", "dbp": "fluid", "hypovolaemia": "fluid", "febrile": "infection", "temp": "infection",
               "multi_system": "infection", "fatigue": "fatigue", "sensor_fault": "sensor", "spe": "radiation"}
REGION2CONCERN = {"lung_left": "respiratory", "lung_right": "respiratory", "trachea": "respiratory", "brain": "fatigue",
                  "kidney_left": "renal_liver", "kidney_right": "renal_liver", "liver": "renal_liver", "skin": "infection",
                  "aorta": "cardio_drift", "vena_cava": "cardio_drift", "arteries": "cardio_drift", "veins": "cardio_drift"}
for _r in ("soleus_left", "soleus_right", "tibia_left", "tibia_right", "femur_left", "femur_right"):
    REGION2CONCERN[_r] = "musculoskeletal"


def kb_meta() -> dict:
    return _G["_meta"] | {"n_concerns": len(_G["concerns"])}


def concern_for(engine, aid: str | None, region: str | None = None, incident: dict | None = None) -> str | None:
    if incident is not None and incident["astronaut_id"] in ("ENV", "CABIN"):
        return "radiation" if incident["astronaut_id"] == "ENV" else "co2"
    if aid and aid in engine.last and engine.last[aid]:
        L = engine.last[aid]
        att = (engine.cabin_state or {}).get("attribution")
        if att and aid in att.get("crew", []) and str(att.get("cause", "")).startswith("environmental") and \
                region in (None, "lung_left", "lung_right", "trachea"):
            return "co2"
        cats = categorise(L["cls"], L["patterns"])
        if region == "heart":
            if any(c in cats for c in ("arrhythmia", "hr")):
                return "cardio_rhythm"
            if any(c in cats for c in ("hypovolaemia", "sbp", "dbp")):
                return "fluid"
            return "cardio_drift"
        if region in REGION2CONCERN:
            return REGION2CONCERN[region]
        for c in cats:
            if c in CAT2CONCERN:
                return CAT2CONCERN[c]
    return REGION2CONCERN.get(region or "")


def _source(key):
    if not key:
        return {"title": "ARES team reasoning (not a published source)", "url": ""}
    return _G["sources"][key]


def _trend(engine, aid, k, z_now):
    rec = list(engine.recent.get(aid, []))
    if len(rec) < 12 or z_now is None:
        return "unknown"
    r = rec[-11]
    v, e, lo, hi = r["v"][k], r["e"][k], r["lo"][k], r["hi"][k]
    if v is None or e is None or lo is None or hi is None or hi == lo:
        return "unknown"
    z_old = (v - e) / ((hi - lo) / 4)
    if abs(z_now) > abs(z_old) + 0.5:
        return "getting worse"
    if abs(z_now) < abs(z_old) - 0.5:
        return "improving"
    return "steady"


def build(engine, aid: str | None, region: str | None = None, incident: dict | None = None,
          concern: str | None = None) -> dict:
    concern = concern or concern_for(engine, aid, region, incident)
    if concern is None:
        return {"concern": None, "note": "No health concern detected for this selection - nothing to advise."}
    c = _G["concerns"][concern]
    t = engine.t
    # ------------------------------------------------ A. what is happening (live data)
    changed, level, label, opened = [], 0, "Normal", None
    if aid in engine.by_id and engine.last.get(aid):
        L = engine.last[aid]
        level, label = L["cls"]["level"], L["cls"]["label"]
        st = L["state"]
        for k, info in L["cls"]["params"].items():
            if info.get("value") is None or (info.get("sustained_sev", 0) < 1 and abs(info.get("z") or 0) < 2):
                continue
            z = info.get("z")
            changed.append({"key": k, "label": PLAIN.get(k, PARAMS[k].label), "value": round(info["value"], 1),
                            "usual": round(info["expected"], 1), "unit": info.get("unit", ""),
                            "z": None if z is None else round(z, 1),
                            "direction": "higher" if (z or 0) > 0 else "lower",
                            "for_min": info.get("sustained_min"), "trend": _trend(engine, aid, k, z)})
        ctx = st["context"]
    else:
        ctx = None
    inc = incident
    if inc is None and aid in engine.active:
        inc = engine.incidents.get(engine.active[aid])
    if inc is not None:
        opened = inc["opened"]
        level = max(level, inc["level"]) if inc["closed"] is None else level
    trends = [x["trend"] for x in changed]
    overall = "getting worse" if "getting worse" in trends else "improving" if trends and all(
        x == "improving" for x in trends) else "steady" if trends else "no live deviation"
    parts = [f"{x['label']} is {x['direction']} than this astronaut's usual ({x['value']} vs {x['usual']} {x['unit']})"
             for x in changed[:3]]
    summary = ("; ".join(parts) + ".") if parts else (
        "No measurement is currently outside this astronaut's normal band." if concern not in ("radiation", "co2",
                                                                                                "musculoskeletal")
        else c["title"] + ".")
    happening = {"summary": summary, "changed": changed, "first_detected_min": opened,
                 "minutes_since": None if opened is None else round(t - opened, 0), "trend": overall,
                 "alert_level": level, "alert_label": label}
    # ------------------------------------------------ B. immediate action (verbatim protocols)
    protos = []
    for pid in c["protocols"]:
        p = engine.kb.by_id.get(pid)
        if p:
            protos.append({"id": p["id"], "title": p["title"], "steps": p["assessment_steps"],
                           "escalate_if": p["escalation_criteria"], "measurements": p.get("additional_measurements", []),
                           "source": p["source"], "approval": p["approval"]})
    comm = engine.mission.status(t)["comm_mode"]
    immediate = {
        "protocols": protos,
        "stop_activity": ("Yes - stop the current activity and rest" if level >= 2 and ctx == "exercise" else
                          "Yes - stay at rest until reviewed" if level >= 2 else "Not required"),
        "notify_cmo": ("Now - critical" if level >= 3 else "Now" if level >= 2 else "At the next routine check" if level == 1
                       else "Not required"),
        "send_to_earth": (("Queued (Earth link down - will send automatically)" if comm == "blackout" else "Yes - sent with priority")
                          if level >= 2 else "Daily summary only"),
        "measurements": list(dict.fromkeys(m for p in protos for m in p["measurements"])),
        "kb_status": engine.kb.meta["status"],
    }
    longterm = [{"text": e["text"], "evidence": e["evidence"],
                 "evidence_label": _G["_meta"]["evidence_levels"][e["evidence"]], "source": _source(e["source"])}
                for e in c["long_term"]]
    escal = list(dict.fromkeys(x for p in protos for x in ([p["escalate_if"]] if isinstance(p["escalate_if"], str)
                                                         else p["escalate_if"])))
    management = c["management"] | {"escalate_if": escal}
    return {"concern": concern, "title": c["title"], "system": c["system"], "regions": c["regions"],
            "what_is_happening": happening, "immediate_action": immediate, "long_term_effects": longterm,
            "long_term_care": management, "kb_version": _G["_meta"]["version"], "kb_status": _G["_meta"]["status"]}


def search(q: str) -> list[dict]:
    q = q.lower()
    out = []
    for k, c in _G["concerns"].items():
        blob = " ".join([c["title"], c["system"], " ".join(e["text"] for e in c["long_term"])]).lower()
        score = sum(w in blob for w in q.split() if len(w) > 2)
        if score:
            out.append({"concern": k, "title": c["title"], "system": c["system"], "score": score})
    return sorted(out, key=lambda x: -x["score"])
