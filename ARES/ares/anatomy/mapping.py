"""Anatomical intelligence mapping: ARES findings -> 3D body regions.

The 3D digital twin never decides anything itself. Every highlight comes from
this module, which converts the outputs of the existing pipeline (classifier,
patterns, behavioral readiness, labs, cabin attribution, radiation) into
region states with an explicit EVIDENCE KIND and DATA CATEGORY.

Honesty rules enforced here (and tested in tests/test_anatomy.py):
  * A region can only be coloured by signals that are physiologically tied to it
    (heart <- HR/HRV/BP/ECG; lungs <- SpO2/RR; kidneys <- creatinine/BUN ...).
  * Organs that ARES does not monitor are shown as "not monitored" (grey), not
    as normal. Failed sensors make their region "unknown" (grey), not normal.
  * Brain = FUNCTIONAL category (vigilance, fatigue, mood); never a lesion.
  * Radiation = body-wide EXPOSURE overlay; no organ is marked injured.
  * Mouse spaceflight findings = RESEARCH EVIDENCE on the matching structure,
    explicitly "not this astronaut", never a severity colour.
  * Lab markers say "laboratory marker", not "organ damage".
"""

from __future__ import annotations

import json
from pathlib import Path

from ares.clinical.log import LAB_ORGAN, LABS
from ares.config import DETECTION, PARAMS

REGIONS_JSON = Path(__file__).resolve().parents[2] / "assets" / "anatomy" / "regions.json"

SEV_STATE = {0: "normal", 1: "observation", 2: "elevated", 3: "critical"}
STATE_RANK = {"not_monitored": -2, "unknown": -1, "normal": 0, "observation": 1, "elevated": 2, "critical": 3}
SYN = "SYNTHETIC SIMULATION DATA"
REAL_NASA = "REAL NASA DATA"
REAL_OTHER = "REAL NON-NASA BIOMEDICAL DATA"
MODEL = "MODEL-GENERATED ESTIMATE"
MIN_QUALITY = 0.6

# region group -> which measured parameters / patterns may drive it
VITAL_RULES = [
    {"regions": ["heart"], "params": ["hr", "hrv_rmssd", "sbp", "dbp"], "system": "Cardiovascular",
     "patterns": ["arrhythmia", "hypovolaemia", "febrile", "hypoxaemia"]},
    {"regions": ["aorta", "vena_cava"], "params": ["sbp", "dbp"], "system": "Cardiovascular (blood pressure)",
     "patterns": ["hypovolaemia"]},
    {"regions": ["lung_left", "lung_right", "trachea"], "params": ["spo2", "rr"], "system": "Respiratory",
     "patterns": ["hypoxaemia", "respiratory"]},
]
LAB_RULES = [
    {"regions": ["kidney_left", "kidney_right"], "labs": ["creatinine", "bun"], "system": "Renal (laboratory markers)"},
    {"regions": ["liver"], "labs": ["alt", "ast"], "system": "Hepatic (laboratory markers)"},
]
# structures for which mouse spaceflight evidence exists (filled from ares/realdata when data are loaded)
EVIDENCE_REGIONS = {"soleus_left", "soleus_right", "gastrocnemius_left", "gastrocnemius_right",
                    "tibia_left", "tibia_right", "femur_left", "femur_right"}


def load_regions() -> dict:
    if not REGIONS_JSON.exists():
        return {"regions": []}
    return json.loads(REGIONS_JSON.read_text())


def _metric(k: str, st: dict, pinfo: dict) -> dict:
    p = PARAMS[k]
    v = st["values"].get(k)
    band = st["band"].get(k, (None, None))
    q = st["quality"].get(k, 0.0)
    info = pinfo.get(k, {})
    return {"key": k, "label": p.label, "unit": p.unit, "value": None if v is None else round(float(v), 2),
            "expected": round(float(st["expected"][k]), 2) if st["expected"].get(k) is not None else None,
            "band": [round(float(band[0]), 2), round(float(band[1]), 2)] if band[0] is not None else None,
            "z": None if st["z"].get(k) is None else round(float(st["z"][k]), 2), "quality": round(float(q), 2),
            "sev": int(info.get("sustained_sev", 0) or 0), "sustained_min": info.get("sustained_min"),
            "source": "measured" if p.measured else "derived estimate", "sensor": p.sensor,
            "trend_per_h": round(float(st["slope_h"].get(k, 0.0)), 3)}


def _projected_sev(m: dict, horizon_h: float = 0.5) -> int:
    """Trend extrapolation (Kalman slope x horizon) against the personal band. MODEL-GENERATED."""
    if m["value"] is None or m["band"] is None:
        return 0
    sd = max((m["band"][1] - m["band"][0]) / 4.0, 1e-6)
    zp = abs(m["value"] + m["trend_per_h"] * horizon_h - m["expected"]) / sd
    return 2 if zp >= DETECTION.z_moderate else 1 if zp >= DETECTION.z_mild else 0


_EVID: dict | None = None


def research_evidence() -> dict:
    """Region -> list of research findings computed by scripts/real_nasa_models.py (empty if not run)."""
    global _EVID
    if _EVID is None:
        f = Path(__file__).resolve().parents[2] / "reports" / "real_nasa_data.json"
        try:
            _EVID = json.loads(f.read_text()).get("research_evidence", {}) if f.exists() else {}
        except (OSError, ValueError):
            _EVID = {}
    return _EVID


def region_states(engine, aid: str) -> dict:
    """Current anatomical state for one astronaut (consumed by the 3D twin)."""
    L = engine.last[aid]
    st, cls = L["state"], L["cls"]
    pinfo = cls.get("params", {})
    pats = {p["id"]: p for p in (L.get("patterns") or [])}
    faults = set(st.get("faults", []))
    out: dict[str, dict] = {}

    def put(rid, state, kind, category, system, evidence, metrics=None, note=None, projected=None):
        cur = out.get(rid)
        if cur and STATE_RANK[cur["state"]] >= STATE_RANK[state]:
            cur["evidence"] += [e for e in evidence if e not in cur["evidence"]]
            return
        out[rid] = {"id": rid, "state": state, "kind": kind, "category": category, "system": system,
                    "evidence": evidence, "metrics": metrics or [], "note": note, "projected_state": projected}

    # ---- measured vital signs (synthetic crew in this demo)
    for rule in VITAL_RULES:
        ms = [_metric(k, st, pinfo) for k in rule["params"]]
        good = [m for m in ms if m["value"] is not None and m["quality"] >= MIN_QUALITY]
        ev = []
        bad_sensors = [m["label"] for m in ms if m not in good]
        for m in good:
            if m["sev"] >= 1:
                ev.append(f"{m['label']} {m['value']} {m['unit']} vs usual {m['expected']} "
                          f"(z={m['z']:+.1f}, sustained {m['sustained_min'] or 0} min)")
        for pid in rule["patterns"]:
            if pid in pats:
                ev.append(f"Pattern: {pats[pid]['name']} (hypothesis, not a diagnosis)")
        if bad_sensors:
            ev.append("Unreliable / missing: " + ", ".join(bad_sensors))
        if not good:
            state = "unknown"
            ev.insert(0, "Insufficient data - sensors unavailable or failed quality checks")
        else:
            sev = max(m["sev"] for m in good)
            state = SEV_STATE[sev]
            if cls["level"] == 3 and sev >= 2:
                state = "critical"
        proj = SEV_STATE[max([_projected_sev(m) for m in good] + [0])] if good else None
        for rid in rule["regions"]:
            put(rid, state, "measured", SYN, rule["system"], list(ev), ms,
                note="Physiological signals associated with this organ system; they do not localise injury.",
                projected=proj)

    # ---- cabin environment attribution (lungs, environmental)
    att = (engine.cabin_state or {}).get("attribution")
    if att and aid in att.get("crew", []) and att["cause"].startswith("environmental"):
        for rid in ("lung_left", "lung_right"):
            if rid in out:
                out[rid]["evidence"].insert(0, "ENVIRONMENTAL: " + att["text"])
                out[rid]["kind"] = "environmental"

    # ---- brain: functional category only
    beh = engine.behavior[aid].assess()
    sources = engine.behavior[aid].series().get("sources", [])
    put("brain", SEV_STATE[min(beh["level"], 2)] if beh["level"] else "normal", "functional",
        SYN if "live" not in sources[-3:] else SYN + " + LIVE TEST", "Behavioral & cognitive (functional)",
        [d["text"] for d in beh["domains"].values()],
        note="Functional health category (vigilance, fatigue, mood, sleep). Not a brain lesion or imaging finding.")

    # ---- labs: kidneys / liver
    lab = engine.clinical[aid].lab_assessment()
    flagged = set(lab.get("flag_keys") or [])
    latest = (lab.get("latest") or {}).get("values", {})
    for rule in LAB_RULES:
        have = [k for k in rule["labs"] if k in latest]
        if not have:
            for rid in rule["regions"]:
                put(rid, "not_monitored", "lab_marker", SYN, rule["system"],
                    ["No in-flight laboratory result recorded yet"],
                    note="No continuous sensor exists for this organ; status comes from lab results when available.")
            continue
        hits = [f for f in lab.get("flags", []) if any(LABS[k][0] in f for k in rule["labs"])]
        state = "observation" if any(k in flagged for k in rule["labs"]) else "normal"
        for rid in rule["regions"]:
            put(rid, state, "lab_marker", SYN, rule["system"],
                hits or [f"{k.upper()} {latest[k]:g} within own pre-flight range" for k in have],
                note="Laboratory marker compared with the astronaut's own pre-flight value. A marker change is "
                     "not evidence of organ damage.")

    # ---- organs ARES does not monitor
    for rid in ("stomach", "esophagus", "intestine_small", "intestine_large", "spleen", "bladder"):
        put(rid, "not_monitored", "none", "-", "Not monitored by ARES",
            ["No sensor or validated association in this prototype"],
            note="Shown for anatomical context only.")

    # ---- sensor faults explicitly
    for f in faults:
        ch = f.split(":")[0]
        if ch in ("spo2", "rr"):
            for rid in ("lung_left", "lung_right"):
                out.get(rid, {}).setdefault("evidence", []).insert(0, f"Sensor fault: {f}")

    # ---- overlays (body-wide, never organ claims)
    ms = engine.mission.status(engine.t)
    dose = engine.dose[aid].snapshot(ms["days_to_mars"], ms["gcr_model_rate_msv_day"])
    temp = _metric("temp", st, pinfo)
    overlays = {
        "radiation": {"kind": "exposure", "category": SYN + " (dosimeter) / MSL-RAD rates (modelled)",
                      "spe_active": bool(engine.spe.active), "shelter": bool(engine.shelter),
                      "pct_career_limit": dose["pct_career_limit"], "dose_rate_msv_day": dose["dose_rate_msv_day"],
                      "career_total_msv": dose["career_total_msv"],
                      "intensity": min(1.0, (dose["dose_rate_msv_day"] / 5.0) if engine.spe.active else dose["pct_career_limit"] / 100.0),
                      "note": "Whole-body exposure. No organ-specific injury is implied; biological risk not computed."},
        "systemic_temperature": {"kind": "measured", "category": SYN, "metric": temp,
                                 "state": SEV_STATE[temp["sev"]] if temp["value"] is not None else "unknown",
                                 "note": "Core temperature estimate (derived); shown body-wide, not at an organ."},
        "immune_labs": {"kind": "lab_marker", "category": SYN,
                        "flags": [f for f in lab.get("flags", [])
                                  if any(LABS[k][0] in f for k, organ in LAB_ORGAN.items() if organ == "systemic")],
                        "note": "Blood/immune markers are systemic; they are not mapped to a single organ."},
    }

    # ---- research evidence (mouse) - filled by ares.realdata when files are present
    evidence = getattr(engine, "organism_evidence", None) or research_evidence()
    for rid in EVIDENCE_REGIONS:
        e = evidence.get(rid)
        if e:
            out.setdefault(rid, {"id": rid, "state": "not_monitored", "kind": "organism_evidence",
                                 "category": REAL_NASA + " (mouse spaceflight studies)", "system": "Musculoskeletal",
                                 "evidence": ["No onboard measurement of this structure for this astronaut"],
                                 "metrics": [], "projected_state": None,
                                 "note": "Research evidence from NASA mouse spaceflight studies (OSDR). It describes what "
                                         "spaceflight did to mice; it is NOT a measurement or risk estimate for this astronaut."})
            out[rid]["research_evidence"] = e

    # ---- emergency focus
    focus = None
    if cls["level"] >= 2:
        cand = [r for r in out.values() if r["state"] in ("critical", "elevated") and r["kind"] != "none"]
        def strength(r):   # largest personal deviation among the metrics driving this region
            return max([abs(m["z"]) for m in r["metrics"] if m.get("z") is not None and m["sev"] >= 1] + [0.0])
        cand.sort(key=lambda r: (-STATE_RANK[r["state"]], -strength(r), r["id"] != "lung_left"))
        if cand:
            focus = {"region": cand[0]["id"], "level": cls["level"], "incident_id": engine.active.get(aid),
                     "label": cls["label"], "reasons": cls["reasons"][:4], "confidence": cls["confidence"],
                     "confidence_label": cls["confidence_label"], "sensor_health": st["sensor_health"]}
    return {"astronaut_id": aid, "t": engine.t, "level": cls["level"], "label": cls["label"],
            "context": st["context"], "regions": out, "overlays": overlays, "focus": focus,
            "comm_mode": ms["comm_mode"], "states": list(STATE_RANK)}


def history_states(engine, aid: str, n: int = 720) -> dict:
    """Per-minute region states for the timeline (recomputed from stored personal bands).

    Historical = what ARES observed this session (synthetic crew). Values are
    reconstructed from stored minute summaries, so z is approximated from the band.
    """
    rec = list(engine.recent[aid])[-n:]
    frames = []
    for r in rec:
        reg = {}
        for rule in VITAL_RULES:
            sevs = []
            for k in rule["params"]:
                v, e, lo, hi = r["v"][k], r["e"][k], r["lo"][k], r["hi"][k]
                if v is None or e is None or lo is None or hi is None:
                    continue
                z = abs(v - e) / max((hi - lo) / 4.0, 1e-6)
                sevs.append(2 if z >= DETECTION.z_moderate else 1 if z >= DETECTION.z_mild else 0)
            state = "unknown" if not sevs else SEV_STATE[max(sevs)]
            if r["level"] == 3 and sevs and max(sevs) >= 2:
                state = "critical"
            for rid in rule["regions"]:
                reg[rid] = state
        frames.append({"t": r["t"], "level": r["level"], "ctx": r["ctx"], "regions": reg})
    incidents = [{"t": i["opened"], "id": i["id"], "peak": i["peak_level"], "kind": "observed",
                  "text": (i.get("report") or {}).get("event", "")} for i in engine.incidents.values()
                 if i["astronaut_id"] == aid]
    sims = [{"t": s["t"], "kind": "simulated", "text": f"Injected: {s['name']}"}
            for s in engine.active_scenarios if s["astronaut_id"] in (aid, None, "crew")]
    return {"astronaut_id": aid, "frames": frames, "markers": incidents + sims,
            "labels": {"historical": "observed this session (synthetic crew)",
                       "predicted": "trend projection +30 min (model-generated)",
                       "simulated": "injected scenario (simulation)"}}
