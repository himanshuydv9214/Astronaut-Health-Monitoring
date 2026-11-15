"""Organ dossiers for the 3D hologram: click an organ -> its actual health events, evidence, guidance and history.

Every value comes from the live engine, the local databases or the onboard knowledge base. Nothing is generated for
display. Each item carries a CATEGORY so the interface can keep apart:
    direct sensor measurement | derived indicator | test result | AI prediction | research evidence (mice) |
    population estimate | laboratory marker
If an organ has no suitable data the dossier says so ("No sufficient monitoring data available for this organ.")
instead of showing a normal state.
"""

from __future__ import annotations

import json

from ares.anatomy.mapping import MIN_QUALITY, SEV_STATE, STATE_RANK, load_regions, region_states, research_evidence
from ares.clinical.log import LABS
from ares.config import PARAMS
from ares.emergency import guidance as G
from ares.emergency import workflow

NO_DATA = "No sufficient monitoring data available for this organ."
CAT_SENSOR = "direct sensor measurement"
CAT_DERIVED = "derived indicator"
CAT_TEST = "test result"
CAT_AI = "AI prediction"
CAT_RESEARCH = "research evidence (mouse spaceflight studies)"
CAT_POP = "population estimate"
CAT_LAB = "laboratory marker"
SYN_SRC = "simulated crew sensors (synthetic data)"

MUSCLES = ["soleus_left", "soleus_right", "gastrocnemius_left", "gastrocnemius_right", "quadriceps_left",
           "quadriceps_right", "hamstrings_left", "hamstrings_right", "tibialis_anterior", "gluteus", "erector_spinae",
           "pectoralis", "deltoid", "arm_muscles", "abdominals", "trapezius", "latissimus", "thigh_other"]
BONES = ["skull", "spine", "ribcage", "pelvis", "femur_left", "femur_right", "tibia_left", "tibia_right", "arm_bones",
         "shoulder_girdle", "skeleton_other"]
GROUPS: dict[str, dict] = {
    "heart": {"label": "Heart", "system": "Cardiovascular", "regions": ["heart"], "kind": "vital",
              "params": ["hr", "hrv_rmssd", "sbp", "dbp"], "patterns": ["arrhythmia", "hypovolaemia", "febrile", "hypoxaemia"],
              "default_concern": "cardio_rhythm",
              "plain": "heart rate, heart-rate variability and blood pressure"},
    "vessels": {"label": "Major blood vessels", "system": "Cardiovascular (blood pressure)",
                "regions": ["aorta", "vena_cava", "arteries", "veins"], "kind": "vital", "params": ["sbp", "dbp"],
                "patterns": ["hypovolaemia"], "default_concern": "cardio_drift", "plain": "blood pressure"},
    "lungs": {"label": "Lungs", "system": "Respiratory", "regions": ["lung_left", "lung_right", "trachea"],
              "kind": "vital", "params": ["spo2", "rr"], "patterns": ["hypoxaemia", "respiratory"],
              "default_concern": "respiratory", "plain": "blood oxygen and breathing"},
    "brain": {"label": "Brain - alertness and cognition", "system": "Behavioral & cognitive (functional)",
              "regions": ["brain"], "kind": "brain", "default_concern": "fatigue",
              "plain": "alertness, fatigue, sleep and reaction tests"},
    "kidneys": {"label": "Kidneys", "system": "Renal (laboratory markers)", "regions": ["kidney_left", "kidney_right"],
                "kind": "lab", "labs": ["creatinine", "bun"], "default_concern": "renal_liver",
                "plain": "kidney blood-test markers"},
    "liver": {"label": "Liver", "system": "Hepatic (laboratory markers)", "regions": ["liver"], "kind": "lab",
              "labs": ["alt", "ast"], "default_concern": "renal_liver", "plain": "liver blood-test markers"},
    "muscles": {"label": "Muscular system", "system": "Musculoskeletal", "regions": MUSCLES, "kind": "muscle",
                "default_concern": "musculoskeletal", "plain": "muscles"},
    "skeleton": {"label": "Skeletal system", "system": "Musculoskeletal", "regions": BONES, "kind": "bone",
                 "default_concern": "musculoskeletal", "plain": "bones"},
    "skin": {"label": "Skin and body temperature", "system": "Whole body (temperature)", "regions": ["skin"],
             "kind": "vital", "params": ["temp"], "patterns": ["febrile"], "default_concern": "infection",
             "plain": "estimated body temperature"},
    "digestive": {"label": "Digestive organs", "system": "Digestive",
                  "regions": ["stomach", "esophagus", "intestine_small", "intestine_large"], "kind": "none"},
    "spleen": {"label": "Spleen", "system": "Immune", "regions": ["spleen"], "kind": "none"},
    "bladder": {"label": "Bladder", "system": "Renal", "regions": ["bladder"], "kind": "none"},
}
REGION_GROUP = {r: g for g, d in GROUPS.items() for r in d["regions"]}
SEVERITY_WORD = {"normal": "normal", "observation": "observation", "elevated": "elevated concern", "critical": "critical",
                 "unknown": "insufficient data", "not_monitored": "insufficient data"}


def _r(x, d=1):
    return None if x is None else round(float(x), d)


def _metrics(engine, aid, keys):
    L = engine.last[aid]
    st, info = L["state"], L["cls"]["params"]
    out = {}
    for k in keys:
        p = PARAMS[k]
        v = st["values"].get(k)
        band = st["band"].get(k, (None, None))
        q = float(st["quality"].get(k, 0.0) or 0.0)
        e = st["expected"].get(k)
        z = st["z"].get(k)
        i = info.get(k, {})
        out[k] = {"key": k, "label": G.PLAIN.get(k, p.label), "unit": p.unit, "current": _r(v), "baseline": _r(e),
                  "band": None if band[0] is None else [_r(band[0]), _r(band[1])],
                  "difference": None if v is None or e is None else _r(v - e),
                  "z": _r(z, 2), "quality": round(q, 2), "reliable": v is not None and q >= MIN_QUALITY,
                  "sev": int(i.get("sustained_sev", 0) or 0), "sustained_min": i.get("sustained_min"),
                  "trend": G._trend(engine, aid, k, z) if z is not None else "unknown",
                  "category": CAT_SENSOR if p.measured else CAT_DERIVED, "sensor": p.sensor,
                  "data_source": SYN_SRC}
    return out


def _overall_trend(ms):
    tr = [m["trend"] for m in ms if m["trend"] != "unknown"]
    if not tr:
        return "unknown"
    if "getting worse" in tr:
        return "worsening"
    if all(t == "improving" for t in tr):
        return "improving"
    return "stable"


def _incident_link(engine, aid, params, pattern_names):
    iid = engine.active.get(aid)
    inc = engine.incidents.get(iid) if iid is not None else None
    if not inc or inc["closed"] is not None:
        return None
    rep = inc.get("report") or {}
    labels = {PARAMS[k].label for k in params}
    hit = any(m.get("parameter") in labels for m in rep.get("abnormal_measurements", []) if
              m.get("z") is not None and abs(m["z"]) >= 2) or any(any(n in r for n in pattern_names)
                                                                  for r in rep.get("reasons", []))
    if not hit:
        return None
    return {"incident_id": inc["id"], "title": rep.get("event"), "level": inc["level"], "opened": inc["opened"],
            "workflow_status": workflow.status_of(inc), "acknowledged": bool(inc.get("acknowledged"))}


def _confidence(engine, aid, ms):
    L = engine.last[aid]
    cls = L["cls"]
    unc = [r for r in cls.get("reasons", []) if "spot-check" in r or "confirm" in r.lower()]
    for m in ms:
        if m["band"] and m["current"] is not None:
            unc.append(f"{m['label']}: personal normal range {m['band'][0]}-{m['band'][1]} {m['unit']}")
    return {"detection_confidence": cls.get("confidence"), "confidence_label": cls.get("confidence_label"),
            "uncertainty": unc[:6],
            "sensor_reliability": {m["key"]: {"quality": m["quality"], "reliable": m["reliable"], "sensor": m["sensor"]}
                                   for m in ms},
            "sensor_health": L["state"].get("sensor_health"),
            "note": "Detection confidence is how sure ARES is that the measurements are genuinely unusual for this "
                    "astronaut (model output); sensor quality is the signal-quality index of each sensor."}


def _ai(engine, aid, rs_regions, group):
    L = engine.last[aid]
    proj = [rs_regions[r].get("projected_state") for r in GROUPS[group]["regions"] if r in rs_regions]
    proj = [p for p in proj if p]
    return {"category": CAT_AI, "risk_30min": _r(L.get("risk"), 3), "anomaly_score": _r(L.get("anomaly"), 3),
            "projected_state_30min": max(proj, key=lambda s: STATE_RANK[s]) if proj else None,
            "note": "Model estimates for the whole astronaut (not organ-specific): 30-minute deterioration risk, "
                    "unusual-pattern score, and where the trend would be in 30 minutes if it continued."}


def _vital_events(engine, aid, group, rs):
    d = GROUPS[group]
    L = engine.last[aid]
    cls = L["cls"]
    ms = _metrics(engine, aid, d["params"])
    pats = [p for p in (L.get("patterns") or []) if p["id"] in d["patterns"]]
    events, covered = [], set()
    t = engine.t

    def sev_state(keys):
        good = [ms[k] for k in keys if ms[k]["reliable"]]
        if not good:
            return "unknown"
        sev = max(m["sev"] for m in good)
        st = SEV_STATE[sev]
        if cls["level"] == 3 and sev >= 2:
            st = "critical"
        return st

    for p in pats:
        keys = [k for k in p.get("evidence", {}) if k in ms] or list(ms)
        covered.update(keys)
        state = sev_state(keys)
        if state in ("normal", "unknown"):
            state = "observation"
        onset = max([ms[k]["sustained_min"] or 0 for k in keys] + [0])
        events.append({"type": "pattern", "key": p["id"], "title": p["name"], "concern": G.CAT2CONCERN.get(p["id"]),
                       "state": state, "params": keys, "detected_at": t - onset, "pattern_evidence": p.get("evidence"),
                       "pattern_note": "Co-deviation pattern recognised by ARES - a hypothesis, not a diagnosis."})
    for k, m in ms.items():
        if k in covered or not m["reliable"] or m["sev"] < 1:
            continue
        direction = "higher" if (m["z"] or 0) > 0 else "lower"
        events.append({"type": "measurement", "key": k, "title": f"{m['label']} {direction} than this astronaut's usual",
                       "concern": G.CAT2CONCERN.get(k), "state": sev_state([k]), "params": [k],
                       "detected_at": t - (m["sustained_min"] or 0)})
    bad = [k for k, m in ms.items() if not m["reliable"]]
    faults = [f for f in L["state"].get("faults", []) if f.split(":")[0] in d["params"]]
    if bad or faults:
        names = ", ".join(ms[k]["label"] for k in bad) if bad else ", ".join(faults)
        spot = [k for k in bad if k in ("sbp", "dbp")]
        events.append({"type": "sensor", "key": "sensor",
                       "title": ("No recent reliable reading: " + names) + (" (blood pressure is a spot-check, not a "
                                                                             "continuous sensor)" if spot else ""),
                       "concern": "sensor", "state": "unknown", "params": bad or [f.split(":")[0] for f in faults],
                       "detected_at": None, "faults": faults,
                       "pattern_note": "A sensor problem is not a health problem; these readings are not used for "
                                       "colouring the organ."})
    att = (engine.cabin_state or {}).get("attribution")
    if group == "lungs" and att and aid in att.get("crew", []) and str(att.get("cause", "")).startswith("environmental"):
        events.append({"type": "environmental", "key": "cabin_co2", "title": "Likely caused by cabin air (CO2)",
                       "concern": "co2", "state": "observation", "params": list(ms), "detected_at": None,
                       "pattern_note": att.get("text")})
    for ev in events:
        sub = [ms[k] for k in ev["params"] if k in ms]
        ev.update({"measurements": {m["key"]: m for m in sub}, "trend": _overall_trend(sub),
                   "incident": _incident_link(engine, aid, ev["params"], [ev["title"]]),
                   "confidence": _confidence(engine, aid, sub),
                   "evidence": _evidence(engine, aid, ev, sub)})
    return events, ms


def _evidence(engine, aid, ev, sub):
    out = []
    for m in sub:
        if m["current"] is None:
            out.append({"text": f"{m['label']}: no reading", "category": m["category"]})
            continue
        dev = "" if m["z"] is None else f" ({abs(m['z']):.1f}x this astronaut's normal variation)"
        out.append({"text": f"{m['label']} {m['current']} {m['unit']} vs usual {m['baseline']} {m['unit']}{dev}"
                            + (f", outside the personal range for {m['sustained_min']} min" if m["sev"] >= 1 and
                               m["sustained_min"] else "") + f"; trend: {m['trend']}",
                    "category": m["category"], "quality": m["quality"]})
    if ev.get("pattern_evidence"):
        out.append({"text": "Pattern '" + ev["title"] + "' links: " + ", ".join(
            f"{G.PLAIN.get(k, k)} (z {v:+.1f})" for k, v in ev["pattern_evidence"].items()), "category": CAT_AI})
    for r in engine.last[aid]["cls"].get("reasons", [])[:4]:
        if any(PARAMS[k].label in r for k in ev["params"]):
            out.append({"text": "Detector: " + r, "category": "detection rule"})
    return out


def _brain(engine, aid, store):
    beh = engine.behavior[aid]
    a = beh.assess()
    ser = beh.series()
    tests = []
    trend = None
    if store is not None:
        from ares.assessments import analysis
        trend = analysis.trends(store, aid, engine)
        for x in store.list(aid=aid, limit=40):
            if x["test_type"] in ("pvt", "wellness_checkin"):
                tests.append(x)
    events = []
    for name, dom in a["domains"].items():
        if dom.get("flag"):
            events.append({"type": "functional", "key": name, "title": {"vigilance": "Slower reaction tests (vigilance)",
                                                                       "fatigue": "High self-rated fatigue",
                                                                       "wellbeing": "Mood / stress outside usual range",
                                                                       "sleep": "Sleep debt"}.get(name, name),
                           "concern": "fatigue", "state": SEV_STATE[min(max(a["level"], 1), 2)], "params": [],
                           "detected_at": None, "measurements": {}, "trend": "unknown", "incident": None,
                           "confidence": None,
                           "evidence": [{"text": dom["text"], "category": CAT_TEST if name in ("vigilance", "fatigue",
                                                                                               "wellbeing")
                                         else CAT_DERIVED}],
                           "pattern_note": "Functional indicator from tests and ratings - not a structural brain finding."})
    latest = next((t for t in tests if t["test_type"] == "pvt" and t["status"] == "completed"), None)
    meas = {}
    if latest:
        full = store.get(latest["test_id"])
        m = full["result"]["metrics"]
        b = ((full["result"].get("baseline") or {}).get("values")) or {}
        for k, lab, unit in (("mean_rt_ms", "Reaction test - average", "ms"), ("lapses", "Reaction test - lapses", ""),
                             ("sd_ms", "Reaction test - variability (SD)", "ms")):
            if m.get(k) is not None:
                meas[k] = {"key": k, "label": lab, "unit": unit, "current": m[k], "baseline": b.get(k),
                           "difference": None if b.get(k) is None else _r(m[k] - b[k]), "category": CAT_TEST,
                           "data_source": f"saved test {latest['test_id']}", "trend": "unknown", "quality": None,
                           "reliable": True, "sev": 0, "band": None, "z": None}
    sl = engine.last[aid]["state"].get("sleep_h_24h")
    if sl is not None:
        meas["sleep_h_24h"] = {"key": "sleep_h_24h", "label": "Sleep in the last 24 h", "unit": "h", "current": _r(sl),
                               "baseline": _r(engine.by_id[aid].sleep_hours), "difference": _r(sl - engine.by_id[aid].sleep_hours),
                               "category": CAT_DERIVED, "data_source": SYN_SRC + " (actigraphy)", "trend": "unknown",
                               "quality": None, "reliable": True, "sev": 0, "band": None, "z": None}
    history = {"saved_tests": tests[:40], "pvt_trend": trend,
               "behavioral_series": {k: ser.get(k) for k in ("pvt_day", "speed", "lapses", "ci_day", "samn_perelli",
                                                             "sleep_day", "sleep_h", "sources")},
               "behavioral_series_note": "Daily battery of the simulated crew model plus live tests ('live' in sources)."}
    model = {"category": "Model-generated assessment", "level": a["level"], "label": a["label"], "note": a.get("note"),
             "flagged": a.get("flagged", [])}
    return events, meas, history, model


def _labs(engine, aid, group):
    d = GROUPS[group]
    cl = engine.clinical[aid]
    lab = cl.lab_assessment()
    pre = cl.preflight_labs
    have = {k: None for k in d["labs"]}
    hist = {k: [] for k in d["labs"]}
    for rec in cl.labs:
        for k in d["labs"]:
            if k in rec["values"]:
                have[k] = rec["values"][k]
                hist[k].append({"t": rec["t"], "value": rec["values"][k]})
    meas = {}
    for k in d["labs"]:
        if have[k] is None:
            continue
        name, unit, rng = LABS[k]
        meas[k] = {"key": k, "label": name, "unit": unit, "current": have[k], "baseline": pre.get(k),
                   "difference": None if pre.get(k) is None else _r(have[k] - pre[k], 2), "band": list(rng),
                   "category": CAT_LAB, "data_source": "lab result entered on this computer (pre-flight value simulated)",
                   "trend": "unknown", "quality": None, "reliable": True, "sev": 1 if k in (lab.get("flag_keys") or []) else 0,
                   "z": None}
    events = []
    for k in d["labs"]:
        if k in (lab.get("flag_keys") or []):
            flag = next((f for f in lab.get("flags", []) if LABS[k][0] in f), LABS[k][0])
            events.append({"type": "lab", "key": k, "title": f"{LABS[k][0]} changed", "concern": "renal_liver",
                           "state": "observation", "params": [k], "detected_at": hist[k][-1]["t"] if hist[k] else None,
                           "measurements": {k: meas[k]}, "trend": "unknown", "incident": None, "confidence": None,
                           "evidence": [{"text": flag, "category": CAT_LAB}],
                           "pattern_note": "Laboratory marker compared with the astronaut's own pre-flight value. A marker "
                                           "change is not evidence of organ damage."})
    return events, meas, {"labs": hist, "preflight": {k: pre.get(k) for k in d["labs"]}}


def _bone_estimate(engine, regions):
    pe = G._G.get("population_estimates", {}).get("bone_density_loss")
    if not pe:
        return None
    day = float(engine.mission.status(engine.t)["mission_day"])
    lo, hi = pe["rate_pct_per_month"]
    months = day / 30.44
    per_region = {}
    for r in regions:
        if r in pe["applies_to"]:
            per_region[r] = {"estimated_change_pct": [_r(-lo * months, 1), _r(-hi * months, 1)], "applies": True}
        else:
            per_region[r] = {"applies": False, "reason": pe["not_applicable"].get(r, "Not covered by the published average.")}
    return {"category": CAT_POP, "title": pe["title"], "mission_day": _r(day, 1),
            "rate_pct_per_month": pe["rate_pct_per_month"], "per_region": per_region, "basis": pe["basis"],
            "caveat": pe["caveat"], "evidence": pe["evidence"], "sources": [G._source(s) for s in pe["sources"]]}


def _activity(engine, aid):
    rec = list(engine.recent.get(aid, []))[-720:]
    if not rec:
        return None
    ex = sum(1 for r in rec if r["ctx"] == "exercise")
    return {"key": "exercise_min_12h", "label": "Exercise time in the last 12 h", "unit": "min", "current": ex,
            "baseline": _r(engine.by_id[aid].exercise_min, 0) if hasattr(engine.by_id[aid], "exercise_min") else None,
            "difference": None, "category": CAT_DERIVED,
            "data_source": SYN_SRC + " (activity context from wearable)", "trend": "unknown", "quality": None,
            "reliable": True, "sev": 0, "band": None, "z": None,
            "note": "Activity only - ARES has no onboard muscle-strength or muscle-mass measurement."}


def _previous_alerts(engine, rt, aid, group):
    d = GROUPS[group]
    labels = {PARAMS[k].label for k in d.get("params", [])}
    words = [w for w in (d.get("plain") or "").split()]
    out = []
    for inc in sorted(engine.incidents.values(), key=lambda i: -i["opened"]):
        if inc["astronaut_id"] != aid:
            continue
        rep = inc.get("report") or {}
        if labels and any(m.get("parameter") in labels and m.get("z") is not None and abs(m["z"]) >= 2
                          for m in rep.get("abnormal_measurements", [])):
            out.append({"source": "this session", "incident_id": inc["id"], "title": rep.get("event"),
                        "opened": inc["opened"], "closed": inc["closed"], "peak_level": inc.get("peak_level"),
                        "status": workflow.status_of(inc)})
    hist = getattr(rt, "history", None)
    if hist is not None and labels:
        with hist.lock:
            rows = hist.db.execute("SELECT session, inc_id, opened, level, status, payload FROM incidents WHERE aid=? AND "
                                   "session<? ORDER BY session DESC, opened DESC LIMIT 200", (aid, hist.session)).fetchall()
        for sess, iid, opened, lvl, status, payload in rows:
            try:
                p = json.loads(payload)
            except ValueError:
                continue
            rep = p.get("report") or {}
            if any(m.get("parameter") in labels and m.get("z") is not None and abs(m["z"]) >= 2
                   for m in rep.get("abnormal_measurements", [])):
                out.append({"source": f"earlier session #{sess}", "incident_id": iid, "title": rep.get("event"),
                            "opened": opened, "closed": p.get("closed"), "peak_level": p.get("peak_level", lvl),
                            "status": status})
    del words
    return out[:30]


def _timeline(engine, aid, group):
    kinds = {"brain": ("pvt", "behavioral"), "kidneys": ("labs",), "liver": ("labs",)}.get(group)
    d = GROUPS[group]
    labels = [G.PLAIN.get(k, PARAMS[k].label) for k in d.get("params", [])] + [PARAMS[k].label for k in d.get("params", [])]
    pats = d.get("patterns", [])
    out = []
    for ev in engine.twins[aid].timeline[::-1]:
        if kinds and ev["kind"] in kinds:
            out.append(ev)
        elif not kinds and (ev["kind"] in ("alert", "baseline") and (ev["kind"] == "baseline" or any(
                x.lower() in ev["text"].lower() for x in labels + pats + ["desaturation", "rhythm", "pressure", "breath"]))):
            out.append(ev)
    return out[:40]


def organ_report(engine, rt, aid: str, region: str) -> dict:
    group = REGION_GROUP.get(region)
    meta = {r["id"]: r for r in load_regions().get("regions", [])}
    if group is None:
        return {"region": region, "group": None, "data_available": False, "message": NO_DATA, "events": []}
    d = GROUPS[group]
    rs = region_states(engine, aid)
    regs = rs["regions"]
    region_info = {r: {"state": regs.get(r, {}).get("state", "not_monitored"), "label": meta.get(r, {}).get("label", r),
                       "kind": regs.get(r, {}).get("kind"), "category": regs.get(r, {}).get("category")}
                   for r in d["regions"]}
    store = getattr(rt, "tests", None)
    events, meas, history, model, extra = [], {}, {}, None, {}
    if d["kind"] == "vital":
        events, ms = _vital_events(engine, aid, group, rs)
        meas = ms
        cols = engine._columns(aid, 720)
        step = max(1, len(cols["t"]) // 360)
        history = {"t": cols["t"][::step], "t0": engine.baseline_end,
                   "series": {k: {"label": G.PLAIN.get(k, PARAMS[k].label), "unit": PARAMS[k].unit,
                                  "value": cols["v"][k][::step], "expected": cols["e"][k][::step],
                                  "lo": cols["lo"][k][::step], "hi": cols["hi"][k][::step],
                                  "category": CAT_SENSOR if PARAMS[k].measured else CAT_DERIVED}
                              for k in d["params"]},
                   "note": "Minute values from this session (up to 12 h); shaded band = the astronaut's personal normal range."}
        extra["ai_predictions"] = _ai(engine, aid, regs, group)
    elif d["kind"] == "brain":
        events, meas, history, model = _brain(engine, aid, store)
    elif d["kind"] == "lab":
        events, meas, history = _labs(engine, aid, group)
    elif d["kind"] == "muscle":
        act = _activity(engine, aid)
        if act:
            meas = {act["key"]: act}
    elif d["kind"] == "bone":
        extra["population_estimate"] = _bone_estimate(engine, d["regions"])
    ev_res = research_evidence()
    research = {r: ev_res[r] for r in d["regions"] if ev_res.get(r)}
    # status of the organ = worst region state (only regions ARES actually evaluates)
    states = [v["state"] for v in region_info.values()]
    state = max(states, key=lambda s: STATE_RANK[s]) if states else "not_monitored"
    if d["kind"] == "vital" and state == "not_monitored":           # e.g. skin: temperature is body-wide, not a region
        rel = [m for m in meas.values() if m["reliable"]]
        state = SEV_STATE[max(m["sev"] for m in rel)] if rel else "unknown"
    for ev in events:
        if STATE_RANK[ev["state"]] > STATE_RANK[state] and ev["type"] not in ("sensor",):
            state = ev["state"]
    direct = [m for m in meas.values() if m.get("category") in (CAT_SENSOR, CAT_TEST, CAT_LAB) and m.get("current") is not None]
    data_available = bool(direct) or (d["kind"] == "brain" and bool(history.get("saved_tests") or
                                                                     (history.get("behavioral_series") or {}).get("pvt_day")))
    if d["kind"] == "vital" and not any(m["reliable"] for m in meas.values()):
        data_available = False
    # guidance per concern (verbatim onboard protocols + knowledge base)
    concerns = list(dict.fromkeys(ev["concern"] for ev in events if ev.get("concern")))
    guide = {c: G.build(engine, aid, d["regions"][0], concern=c) for c in concerns if c in G._G["concerns"]}
    reference = None
    if not concerns and d.get("default_concern"):
        reference = G.build(engine, aid, d["regions"][0], concern=d["default_concern"])
    active = [e for e in events if e["type"] != "sensor" and e["state"] in ("observation", "elevated", "critical")]
    for i, ev in enumerate(events):
        ev["event_id"] = f"{aid}-{group}-{ev['type']}-{ev['key']}".upper()
        ev["astronaut_id"] = aid
        ev["system"] = d["system"]
        ev["anatomical_region"] = group
        ev["regions"] = d["regions"]
        ev["severity"] = SEVERITY_WORD[ev["state"]]
        ev["status"] = "active" if ev in active else "data quality" if ev["type"] == "sensor" else "monitoring"
        ev["data_source"] = SYN_SRC if d["kind"] == "vital" else ev.get("data_source", "local records")
        g = guide.get(ev.get("concern"))
        ev["recommended_actions"] = (g or {}).get("immediate_action", {}).get("protocols", [])
        ev["long_term_considerations"] = (g or {}).get("long_term_effects", [])
    what = _what(d, state, events, meas, data_available)
    return {"astronaut_id": aid, "astronaut_name": engine.by_id[aid].name, "region": region, "group": group,
            "label": d["label"], "system": d["system"], "regions": region_info, "state": state,
            "severity": SEVERITY_WORD[state], "active_alert": bool(active), "active_events": len(active),
            "data_available": data_available, "message": None if data_available else NO_DATA,
            "what_is_happening": what, "events": events, "measurements": meas, "history": history,
            "model_assessment": model, "previous_alerts": _previous_alerts(engine, rt, aid, group) if d["kind"] == "vital" else [],
            "timeline": _timeline(engine, aid, group), "guidance": guide, "reference_guidance": reference,
            "research_evidence": research, "t": engine.t, "t0": engine.baseline_end,
            "categories_legend": [CAT_SENSOR, CAT_DERIVED, CAT_TEST, CAT_LAB, CAT_AI, CAT_RESEARCH, CAT_POP],
            "kb_status": G._G["_meta"]["status"], **extra}


def _what(d, state, events, meas, available):
    if not available and not events:
        if d["kind"] == "none":
            return "ARES has no sensor and no validated measurement for this organ. It is shown for anatomical context only."
        if d["kind"] == "muscle":
            return ("ARES has no onboard measurement of muscle strength or mass. Shown below: activity time from the "
                    "wearable and NASA mouse research, clearly labelled - not a finding about this astronaut.")
        if d["kind"] == "bone":
            return ("ARES has no onboard bone measurement (bone density can only be measured on the ground). Shown below: "
                    "a published population-average estimate and NASA mouse research, clearly labelled - not a finding "
                    "about this astronaut.")
        if d["kind"] == "lab":
            return f"No in-flight {d['plain']} have been recorded yet, so there is nothing to compare."
        return NO_DATA
    act = [e for e in events if e["status"] == "active"]
    if not available and d["kind"] == "vital":
        return (f"There is no recent reliable reading of the {d['plain']}, so ARES cannot say whether it is normal. The "
                "organ is shown grey (insufficient data), not as normal.")
    if not act:
        return f"No unusual change detected in the {d['plain']} - the readings are within this astronaut's usual range."
    parts = []
    for e in act[:3]:
        parts.append(e["title"])
    return (f"ARES has detected an unusual change in the astronaut's {d['plain']}: " + "; ".join(parts) + ". "
            "This describes the measurements, not a diagnosis.")


def organs_summary(engine, aid: str) -> dict:
    """Every organ group with its state and number of active events (for the event list next to the hologram)."""
    rs = region_states(engine, aid)["regions"]
    out = []
    for g, d in GROUPS.items():
        states = [rs.get(r, {}).get("state", "not_monitored") for r in d["regions"]]
        st = max(states, key=lambda s: STATE_RANK[s])
        out.append({"group": g, "label": d["label"], "state": st, "regions": d["regions"],
                    "focus_region": next((r for r in d["regions"] if rs.get(r, {}).get("state") == st), d["regions"][0])})
    out.sort(key=lambda x: -STATE_RANK[x["state"]])
    return {"astronaut_id": aid, "t": engine.t, "organs": out}
