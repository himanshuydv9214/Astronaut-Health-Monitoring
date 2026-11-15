"""ARES engine: orchestrates every layer once per mission minute.

  acquisition (sim) -> signal quality -> digital twin -> features
  -> anomaly model + risk forecaster -> correlation patterns
  -> emergency classifier -> incidents/reports/protocols
  -> mission context + comms queue + radiation tracking
"""

from __future__ import annotations

import itertools
import math
from collections import deque

import numpy as np

import hashlib
import json
from pathlib import Path

from ares.behavioral.model import READINESS, BehavioralProfile, BehavioralRecord
from ares.clinical.log import ClinicalLog
from ares.environment.cabin import CabinMonitor, CabinSimulator
from ares.behavioral.pvt import pvt_stats, score_pvt
from ares.behavioral.simulate import simulate_checkin, simulate_pvt
from ares.config import DISCLAIMER, PARAMS, SIM, STORM_SHELTER_SPE_FACTOR, VITAL_KEYS
from ares.emergency.classifier import LEVEL_LABELS, EmergencyClassifier
from ares.emergency.protocols import ProtocolKB, load_inventory
from ares.emergency.report import build_report, categorise
from ares.intelligence.correlation import RollingCorrelation, match_patterns
from ares.intelligence.explain import explain_state
from ares.intelligence.features import FeatureBuilder
from ares.intelligence.models import AnomalyModel, RiskForecaster
from ares.intelligence.news2 import news2
from ares.mission.comms import CommQueue
from ares.mission.context import MissionContext
from ares.radiation.dose import DoseTracker, SPEDetector
from ares.radiation.donki import load_cached
from ares.simulation.physiology import CrewSimulator
from ares.simulation.profiles import AstronautProfile, get_crew
from ares.simulation.scenarios import UI_SCENARIO_KEYS, build_scenario
from ares.twin.twin import DigitalTwin

PRIORITY_BY_LEVEL = {1: 3, 2: 2, 3: 1}


def _num(x):
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return None if math.isnan(x) else round(float(x), 3)
    return x


class AresEngine:
    def __init__(self, crew: list[AstronautProfile] | None = None, seed: int = SIM.seed, demo_start_day: float = 200.0,
                 baseline_days: float = 2.0, with_ecg: bool = True, load_models: bool = True, record_truth: bool = False,
                 persist: bool = False):
        self.crew = crew or get_crew()
        self.by_id = {p.id: p for p in self.crew}
        self.sim = CrewSimulator(self.crew, seed)
        self.mission = MissionContext(start_day=demo_start_day - baseline_days, crew_size=len(self.crew))
        self.twins = {p.id: DigitalTwin(p.id) for p in self.crew}
        self.fbs = {p.id: FeatureBuilder() for p in self.crew}
        self.clfs = {p.id: EmergencyClassifier() for p in self.crew}
        self.corr = {p.id: RollingCorrelation() for p in self.crew}
        self.dose = {p.id: DoseTracker(p.prior_career_dose_msv) for p in self.crew}
        self.spe = SPEDetector()
        self.comms = CommQueue()
        self.kb = ProtocolKB()
        self.inventory = load_inventory()
        self.anomaly = AnomalyModel.load() if load_models else AnomalyModel()
        self.forecaster = RiskForecaster.load() if load_models else RiskForecaster()
        self.with_ecg = with_ecg
        self.record_truth = record_truth
        self.truth_log: list[dict] = []
        self.t = 0.0
        self.shelter = False
        self.incidents: dict[int, dict] = {}
        self.active: dict[str, int] = {}
        self._inc_ids = itertools.count(1)
        self.recent = {p.id: deque(maxlen=720) for p in self.crew}   # 12 h of minute history (3D timeline scrubbing)
        self.last = {p.id: {} for p in self.crew}
        self.ecg = {p.id: None for p in self.crew}
        self.post_event_until: dict[str, float] = {}
        self.log: deque = deque(maxlen=200)
        self.active_scenarios: list[dict] = []
        self.pvt_runs: dict[str, list[dict]] = {}
        self.baseline_end = baseline_days * 1440
        # behavioral channel (private: astronaut + CMO)
        self.behavior = {p.id: BehavioralProfile(p.id, sleep_need_h=p.sleep_hours) for p in self.crew}
        self._brng = np.random.default_rng(seed + 77)
        self._base_rt = {p.id: float(self._brng.uniform(220, 270)) for p in self.crew}
        self._debt = {p.id: 0.0 for p in self.crew}
        self._last_test_day = {p.id: -1 for p in self.crew}
        # model monitoring
        self._anom_hist: deque = deque(maxlen=1440 * len(self.crew))
        self._ood_hist: deque = deque(maxlen=1440 * len(self.crew))
        rp = Path(__file__).resolve().parents[1] / "models" / "feature_ranges.json"
        self._ranges = json.loads(rp.read_text()) if rp.exists() else {}
        # cabin environment + clinical (symptoms / labs)
        self.cabin_sim = CabinSimulator(seed + 5)
        self.cabin = CabinMonitor()
        self.cabin_state: dict = {}
        self._headache_reported: set = set()
        lr = np.random.default_rng(seed + 9)
        self.clinical = {p.id: ClinicalLog(p.id, preflight_labs={
            "wbc": round(float(lr.normal(6.5, 1.0)), 1), "lymphocytes": round(float(lr.normal(2.0, 0.4)), 2),
            "neutrophils": round(float(lr.normal(3.8, 0.7)), 2), "crp": round(float(abs(lr.normal(1.0, 0.5))), 2),
            "creatinine": round(float(lr.normal(0.95, 0.12)), 2), "bun": round(float(lr.normal(14, 3)), 1),
            "alt": round(float(lr.normal(24, 6)), 0), "ast": round(float(lr.normal(23, 5)), 0)})
            for p in self.crew}
        self.store = None
        if persist:
            from ares.storage import LocalStore
            self.store = LocalStore()
        self._acquire_baseline()
        self._seed_behavioral_history()

    # ------------------------------------------------------------------ lifecycle
    def _acquire_baseline(self) -> None:
        """Baseline acquisition period (simulated early-flight data, fast mode, no alerts)."""
        ecg, self.with_ecg = self.with_ecg, False
        while self.t < self.baseline_end:
            self.tick(alerts=False)
        self.with_ecg = ecg
        self.truth_log.clear()   # baseline-acquisition minutes are never used for evaluation
        for tw in self.twins.values():
            tw.baseline.freeze_premission()
            tw.add_event(self.t, "baseline", "Personal baselines frozen as mission reference", 0)
        self._log("Baseline acquisition complete (simulated). Live monitoring started.")

    def _log(self, text: str, level: int = 0) -> None:
        self.log.appendleft({"t": self.t, "text": text, "level": level})
        if getattr(self, "store", None) is not None:
            self.store.append("events", self.t, "SYS", {"text": text, "level": level})

    # ------------------------------------------------------------------ main step
    def tick(self, alerts: bool = True) -> None:
        t = self.t
        ms = self.mission.status(t)
        modelled = ms["gcr_model_rate_msv_day"]
        att = STORM_SHELTER_SPE_FACTOR if self.shelter else 1.0
        samples = self.sim.step(t, with_ecg=self.with_ecg, base_dose_rate=modelled, spe_attenuation=att)
        n_ex = sum(1 for a in self.last if self.last[a] and self.last[a]["state"]["context"] == "exercise")
        co2_extra = sum(e.co2_extra_mmhg * e.envelope(t) for e in self.sim.crew_effects)
        self.cabin.update(self.cabin_sim.step(t, n_ex, 1.0, co2_extra))
        spe_active = self.spe.update(float(np.mean([s.dose_rate_msv_day for s in samples.values()])), modelled)

        for aid, s in samples.items():
            tw = self.twins[aid]
            st = tw.observe(s)
            feats = self.fbs[aid].build(st)
            an = self.anomaly.score(feats) if alerts else None
            risk = self.forecaster.predict(feats) if alerts else None
            zb = {k: feats[f"zb_{k}"] for k in VITAL_KEYS}
            pats = match_patterns(zb, st, feats)
            cls = self.clfs[aid].classify(st, an, risk, pats).to_dict()
            self.corr[aid].update(st)
            n2 = news2(st["values"]) if st["context"] in ("sleep", "rest") else None
            self.dose[aid].update(s.dose_rate_msv_day, modelled, SIM.sample_period_min, spe_active)
            if s.ecg is not None:
                self.ecg[aid] = s.ecg
            self.last[aid] = {"state": st, "feats": feats, "anomaly": an, "risk": risk, "patterns": pats,
                              "cls": cls, "news2": n2}
            self.recent[aid].append({
                "t": t, "ctx": st["context"], "level": cls["level"], "risk": _num(risk), "anomaly": _num(an),
                "v": {k: _num(st["values"][k]) for k in VITAL_KEYS},
                "e": {k: _num(st["expected"][k]) for k in VITAL_KEYS},
                "lo": {k: _num(st["band"][k][0]) for k in VITAL_KEYS},
                "hi": {k: _num(st["band"][k][1]) for k in VITAL_KEYS},
                "q": {k: _num(st["quality"][k]) for k in VITAL_KEYS},
                "dose": round(s.dose_rate_msv_day, 2),
            })
            if self.record_truth:
                self.truth_log.append({"t": t, "aid": aid, "pred": cls["level"], "cand": cls["candidate_level"],
                                       "truth": s.truth["level"], "events": s.truth["events"],
                                       "faults": s.truth["sensor_faults"], "risk": risk, "anomaly": an,
                                       "news2": n2["score"] if n2 else None, "ctx": st["context"],
                                       "sensor_alert": cls["sensor_alert"], "spe": self.spe.active,
                                       "v": {k: st["values"][k] for k in VITAL_KEYS},
                                       "age": {k: st["age_min"][k] for k in VITAL_KEYS},
                                       "feats": feats})
            if alerts:
                self._incident_logic(aid, t, cls, pats, st, ms, an, risk, n2, feats)
                self._monitor(an, feats)
                if self.store is not None:
                    self.store.append("vitals", t, aid, {"lvl": cls["level"], "ctx": st["context"],
                                                         "v": {k: _num(st["values"][k]) for k in VITAL_KEYS},
                                                         "q": {k: round(st["quality"][k], 2) for k in VITAL_KEYS},
                                                         "risk": _num(risk), "anom": _num(an)})
                self._behavioral_daily(aid, t, st)

        if alerts:
            self._spe_logic(t, spe_active, ms)
            self._cabin_logic(t)
            if int(t) % 60 == 0:
                worst = max(self.last[a]["cls"]["level"] for a in self.last)
                self.comms.enqueue(4, t, "telemetry", f"Routine crew health summary (worst level {worst})")
        self.comms.step(t, ms["comm_mode"], ms["one_way_light_time_min"])
        if self.store is not None and int(t) % 10 == 0:
            self.store.commit()
        self.t += SIM.sample_period_min

    # ------------------------------------------------------------------ incidents
    def _incident_logic(self, aid, t, cls, pats, st, ms, an, risk, n2, feats) -> None:
        lvl = cls["level"]
        inc_id = self.active.get(aid)
        prof = self.by_id[aid]
        if lvl >= 1 and inc_id is None:
            inc_id = next(self._inc_ids)
            self.active[aid] = inc_id
            self.incidents[inc_id] = {"id": inc_id, "astronaut_id": aid, "opened": t, "closed": None, "level": lvl,
                                      "peak_level": lvl, "acknowledged": False, "history": [(t, lvl)], "report": None}
            self._notify(aid, t, lvl, cls, pats, inc_id, opened=True)
        elif inc_id is not None:
            inc = self.incidents[inc_id]
            lvl = max(lvl, inc.get("floor", 0))      # crew escalation is a floor until the incident is reviewed
            if lvl != inc["level"]:
                inc["history"].append((t, lvl))
                if lvl > inc["level"]:
                    inc["acknowledged"] = False
                    self._notify(aid, t, lvl, cls, pats, inc_id, opened=False)
                inc["level"] = lvl
                inc["peak_level"] = max(inc["peak_level"], lvl)
            if lvl == 0:
                inc["closed"] = t
                del self.active[aid]
                self.post_event_until[aid] = t + 180
                self.twins[aid].add_event(t, "resolved", f"Incident #{inc_id} resolved; post-event monitoring 3 h", 0)
                self.comms.enqueue(3, t, "incident_resolved", f"#{inc_id} {prof.name}: resolved (peak L{inc['peak_level']})", aid)
                self._log(f"{prof.name}: incident #{inc_id} resolved (peak level {inc['peak_level']})", 0)
                return
        if inc_id is not None:
            inc = self.incidents[inc_id]
            if inc["report"] is None or int(t) % 5 == 0 or inc["history"][-1][0] == t:
                inc["report"] = self._report(aid, t, cls, pats, st, ms, an, risk, n2, feats)

    def _notify(self, aid, t, lvl, cls, pats, inc_id, opened):
        prof = self.by_id[aid]
        what = pats[0]["name"] if pats else ("sensor reliability" if cls["sensor_alert"] and lvl == 1 else
                                              ", ".join(PARAMS[k].label for k in cls["params"]) or "deviation")
        verb = "opened" if opened else "escalated"
        self.twins[aid].add_event(t, "alert", f"#{inc_id} {verb}: L{lvl} {LEVEL_LABELS[lvl]} - {what}", lvl)
        self.comms.enqueue(PRIORITY_BY_LEVEL[lvl], t, "medical_event",
                           f"#{inc_id} {prof.name}: L{lvl} {LEVEL_LABELS[lvl]} - {what}", aid)
        self._log(f"{prof.name}: incident #{inc_id} {verb} - L{lvl} {LEVEL_LABELS[lvl]} ({what})", lvl)

    def _report(self, aid, t, cls, pats, st, ms, an, risk, n2, feats) -> dict:
        cats = categorise(cls, pats)
        protos = self.kb.for_category(cats, cls["level"])
        shap_top = self.forecaster.explain(feats) if self.forecaster.ready else []
        expl = explain_state(st, cls, shap_top)
        p = self.by_id[aid]
        rep = build_report(astronaut={"id": p.id, "name": p.name, "role": p.role}, t=t, cls=cls, patterns=pats,
                           state=st, categories=cats, protocols=protos, explanation=expl, mission=ms,
                           anomaly=an, risk=risk, news2=n2)
        rep["explanation"] = expl
        att = (self.cabin_state or {}).get("attribution")
        if att and aid in att.get("crew", []) and att["cause"].startswith("environmental"):
            rep["reasons"].append("ENVIRONMENTAL ATTRIBUTION: " + att["text"])
            rep["potential_risk_category"].insert(0, "Cabin environment (CO2) - likely cause")
            if not any(p["id"] == "ENV-01" for p in rep["recommended_protocols"]):
                p = self.kb.by_id["ENV-01"]
                rep["recommended_protocols"].insert(0, {"id": p["id"], "title": p["title"], "steps": p["assessment_steps"],
                                                        "escalation": p["escalation_criteria"], "source": p["source"],
                                                        "approval": p["approval"]})
        patient = self.by_id[aid]
        if "CMO" in patient.role and cls["level"] >= 2:
            backup = next((c for c in self.crew if c.id != aid and "Commander" in c.role), None)
            msg = (f"PATIENT IS THE CREW MEDICAL OFFICER - backup responder: {backup.name} ({backup.role}). "
                   "ARES guidance and protocols are addressed to the backup.") if backup else \
                "PATIENT IS THE CREW MEDICAL OFFICER - designate a backup responder."
            rep["reasons"].insert(0, msg)
            rep["crew_notification"] += " - CMO is the patient: backup responder takes over"
        sym = self.clinical[aid].active_symptoms(t)
        if sym:
            rep["reasons"].append("Crew-reported symptoms (24 h): " + ", ".join(s.replace("_", " ") for s in sym))
            z_t = st["z"].get("temp") or 0
            if "fever_chills" in sym and z_t >= 2:
                rep["reasons"].append(f"Reported fever/chills corroborates temperature above personal baseline (z={z_t:+.1f})")
        rep["symptoms_24h"] = sym
        return rep

    def _spe_logic(self, t, active, ms) -> None:
        env = self.active.get("ENV")
        if active and env is None:
            inc_id = next(self._inc_ids)
            self.active["ENV"] = inc_id
            protos = [self.kb.by_id["RAD-01"]]
            self.incidents[inc_id] = {
                "id": inc_id, "astronaut_id": "ENV", "opened": t, "closed": None, "level": 2, "peak_level": 2,
                "acknowledged": False, "history": [(t, 2)],
                "report": {"event": "EVENT: RADIATION ENVIRONMENT EVENT (SOLAR PARTICLE EVENT)", "level": 2,
                           "level_label": "Environmental - crew protective action",
                           "reasons": ["Crew dosimeter rate > 3x modelled GCR rate for >= 5 min"],
                           "recommended_protocols": [{"id": p["id"], "title": p["title"], "steps": p["assessment_steps"],
                                                      "escalation": p["escalation_criteria"], "source": p["source"],
                                                      "approval": p["approval"]} for p in protos],
                           "crew_notification": "ALL CREW (radiation alarm)", "earth_communication_priority": "P2 priority",
                           "disclaimer": "Measured dose is from SIMULATED dosimeters. Biological risk is not inferred."}}
            for tw in self.twins.values():
                tw.add_event(t, "radiation", f"#{inc_id} Solar particle event detected - shelter advised", 2)
            self.comms.enqueue(2, t, "radiation_event", f"#{inc_id} SPE detected, dose rate elevated; crew sheltering advised")
            self._log(f"Radiation: SPE detected (incident #{inc_id}) - storm shelter advised", 2)
        elif not active and env is not None:
            inc = self.incidents[env]
            inc["closed"] = t
            inc["level"] = 0
            del self.active["ENV"]
            ev = {a: round(self.dose[a].max_event_dose, 1) for a in self.dose}
            self.comms.enqueue(3, t, "radiation_event", f"#{env} SPE ended; event dose (mSv): {ev}")
            self._log(f"Radiation: SPE ended. Event dose per crew (mSv): {ev}", 0)

    # ------------------------------------------------------------------ controls
    def trigger(self, key: str, astronaut_id: str | None = None) -> dict:
        sc = build_scenario(key, self.t + 1)
        aid = astronaut_id or self.crew[0].id
        self.sim.apply(sc, aid)
        if sc.force_blackout:
            self.mission.forced_blackout = True
        self.active_scenarios.append({"key": key, "name": sc.name, "astronaut_id": aid, "t": self.t})
        self._log(f"[SIMULATION] Scenario injected: {sc.name} -> {self.by_id[aid].name if not sc.effects or not sc.effects[0].crew_wide else 'crew-wide'}")
        return {"ok": True, "scenario": sc.name, "description": sc.description}

    def clear_scenarios(self) -> None:
        self.sim.clear()
        self.mission.forced_blackout = False
        self.active_scenarios.clear()
        self._log("[SIMULATION] All scenarios cleared (physiology returns to baseline)")

    def set_comm_override(self, mode: str | None) -> None:
        self.mission.operator_mode = mode if mode in ("connected", "delay", "blackout") else None
        self._log(f"Comm override: {self.mission.operator_mode or 'auto'}")

    def set_shelter(self, on: bool) -> None:
        self.shelter = bool(on)
        self._log("Crew in storm shelter" if on else "Crew left storm shelter")

    def acknowledge(self, inc_id: int) -> bool:
        if inc_id in self.incidents:
            self.incidents[inc_id]["acknowledged"] = True
            self._log(f"Incident #{inc_id} acknowledged by crew")
            return True
        return False

    def set_mission_day(self, day: float) -> None:
        self.mission.start_day = day - self.t / 1440.0
        self._log(f"Mission day set to {day:.0f}")

    # ------------------------------------------------------------------ views
    def crew_summary(self) -> list[dict]:
        ms = self.mission.status(self.t)
        out = []
        for p in self.crew:
            L = self.last[p.id]
            if not L:
                continue
            st, cls = L["state"], L["cls"]
            out.append({
                "id": p.id, "name": p.name, "role": p.role, "level": cls["level"], "label": cls["label"],
                "confidence": cls["confidence"], "context": st["context"], "sensor_health": st["sensor_health"],
                "values": {k: _num(st["values"][k]) for k in VITAL_KEYS},
                "z": {k: _num(st["z"][k]) for k in VITAL_KEYS},
                "risk": _num(L["risk"]), "anomaly": _num(L["anomaly"]),
                "news2": L["news2"], "sleep_h_24h": _num(st["sleep_h_24h"]),
                "dose": self.dose[p.id].snapshot(ms["days_to_mars"], ms["gcr_model_rate_msv_day"]),
                "incident": self.active.get(p.id), "post_event": self.t < self.post_event_until.get(p.id, -1),
            })
        return out

    def astronaut_detail(self, aid: str) -> dict:
        p = self.by_id[aid]
        L = self.last[aid]
        st = L["state"]
        tw = self.twins[aid]
        ecg = self.ecg[aid]
        expl = explain_state(st, L["cls"], self.forecaster.explain(L["feats"]) if self.forecaster.ready else [])
        return {
            "profile": {"id": p.id, "name": p.name, "role": p.role, "age": p.age, "notes": p.notes,
                        "history": p.medical_history, "simulated": True},
            "recent": self._columns(aid),
            "ecg": None if ecg is None else {"fs": SIM.ecg_fs, "mv": [round(float(x), 3) for x in ecg[::2]],
                                             "proc": st.get("ecg_extra"), "hr_source": st["hr_source"]},
            "classification": L["cls"], "patterns": L["patterns"], "explanation": expl,
            "correlations": self.corr[aid].matrix(), "faults": st["faults"], "quality": st["quality"],
            "slopes": {k: {"slope_h": round(st["slope_h"][k], 3), "sd_h": round(st["slope_sd_h"][k], 3)} for k in VITAL_KEYS},
            "baselines": {k: {"expected": round(st["expected"][k], 2), "lo": round(st["band"][k][0], 2),
                              "hi": round(st["band"][k][1], 2), "n": tw.baseline.post[(k, st["context"])].n,
                              "measured": PARAMS[k].measured, "sensor": PARAMS[k].sensor, "unit": PARAMS[k].unit,
                              "label": PARAMS[k].label} for k in VITAL_KEYS},
            "drift": tw.drift_summary(), "longitudinal": tw.longitudinal()[-14:], "timeline": tw.timeline[-40:][::-1],
            "news2": L["news2"], "behavioral": self.behavioral_view(aid), "clinical": self.clinical[aid].view(self.t),
        }

    def _columns(self, aid: str, n: int = 240) -> dict:
        rec = list(self.recent[aid])[-n:]
        cols = {"t": [r["t"] for r in rec], "level": [r["level"] for r in rec], "risk": [r["risk"] for r in rec],
                "anomaly": [r["anomaly"] for r in rec], "ctx": [r["ctx"] for r in rec], "dose": [r["dose"] for r in rec]}
        for f in ("v", "e", "lo", "hi"):
            cols[f] = {k: [r[f][k] for r in rec] for k in VITAL_KEYS}
        return cols

    def incident_summary(self, i: dict) -> dict:
        return {k: i[k] for k in ("id", "astronaut_id", "opened", "closed", "level", "peak_level", "acknowledged")} | {
            "event": (i.get("report") or {}).get("event"), "history": i["history"][-8:]}

    def snapshot(self, selected: str | None = None) -> dict:
        ms = self.mission.status(self.t)
        sel = selected if selected in self.by_id else self.crew[0].id
        incs = sorted(self.incidents.values(), key=lambda i: (i["closed"] is not None, -i["level"], -i["opened"]))
        cached = load_cached()
        return {
            "t": self.t, "demo_minute": self.t - self.baseline_end, "mission": ms, "crew": self.crew_summary(),
            "selected": sel, "detail": self.astronaut_detail(sel),
            "incidents": [self.incident_summary(i) for i in incs[:25]],
            "active_reports": {str(i["id"]): i["report"] for i in incs if i["closed"] is None and i.get("report")},
            "comms": self.comms.snapshot(), "comms_pending": self.comms.pending(),
            "shelter": self.shelter, "spe_active": self.spe.active, "log": list(self.log)[:60],
            "scenarios": [{"key": k, "name": build_scenario(k).name, "description": build_scenario(k).description}
                          for k in UI_SCENARIO_KEYS],
            "cabin": (self.cabin_state or {}) | {"series": self.cabin.series()},
            "behavioral": {p.id: {"level": a["level"], "label": a["label"]}
                           for p in self.crew for a in [self.behavior[p.id].assess()]},
            "active_scenarios": self.active_scenarios,
            "models": {"anomaly": self.anomaly.ready, "forecaster": self.forecaster.ready,
                       "anomaly_meta": self.anomaly.meta, "forecaster_meta": self.forecaster.meta},
            "donki": None if not cached else {"source": cached.get("source"), "fetched": cached.get("fetched"),
                                              "n": len(cached.get("events", [])), "events": cached.get("events", [])[-8:]},
            "disclaimer": DISCLAIMER,
        }

    # ------------------------------------------------------------------ behavioral channel
    def _strain(self, aid: str) -> float:
        sim = self.sim.sims[aid]
        return max([e.behavioral_strain * e.envelope(self.t) for e in sim.effects] + [0.0])

    def _record_behavioral(self, aid: str, day: float, sleep_h: float, strain: float, source: str = "simulated",
                           pvt: dict | None = None, checkin: dict | None = None) -> dict:
        need = self.behavior[aid].sleep_need_h
        self._debt[aid] = max(0.0, self._debt[aid] * 0.85 + max(0.0, need - sleep_h))
        pvt = pvt or simulate_pvt(self._brng, self._base_rt[aid], self._debt[aid], strain)
        checkin = checkin or simulate_checkin(self._brng, sleep_h, need, self._debt[aid], strain)
        return self.behavior[aid].add(BehavioralRecord(day, pvt, checkin, sleep_h, source))

    def _seed_behavioral_history(self) -> None:
        """10 days of SIMULATED prior behavioral records so personal baselines exist at demo start."""
        day0 = self.mission.status(self.t)["mission_day"]
        for p in self.crew:
            for d in range(10, 0, -1):
                sl = p.sleep_hours + float(self._brng.normal(-0.2, 0.35))
                self._record_behavioral(p.id, day0 - d, sl, 0.0)
            self._last_test_day[p.id] = int(day0)

    def _behavioral_daily(self, aid: str, t: float, st: dict) -> None:
        """Morning test battery at each astronaut's wake time (simulated responses)."""
        p = self.by_id[aid]
        wake = (p.sleep_start_min + p.sleep_hours * 60) % 1440
        day = int(self.mission.status(t)["mission_day"])
        if day == self._last_test_day[aid] or abs((t % 1440) - (wake + 20)) > 0.5:
            return
        self._last_test_day[aid] = day
        sleep_h = st.get("sleep_h_24h") or p.sleep_hours
        before = self.behavior[aid].assess()["level"]
        a = self._record_behavioral(aid, self.mission.status(t)["mission_day"], sleep_h, self._strain(aid))
        self._behavioral_change(aid, t, before, a)

    def _behavioral_change(self, aid, t, before, a):
        if a["level"] != before:
            p = self.by_id[aid]
            self.twins[aid].add_event(t, "behavioral", f"Behavioral readiness: {a['label']} ({', '.join(a['flagged'])})",
                                      min(a["level"], 1))
            self._log(f"{p.name}: behavioral readiness {READINESS[before]} -> {a['label']} (private to CMO)", min(a["level"], 1))
            if a["level"] >= 1:
                # only the category leaves the vehicle - no scores, no free text
                self.comms.enqueue(3, t, "behavioral", f"{p.name}: {a['earth_summary']}", aid)
        if self.store is not None:
            self.store.append("behavioral", t, aid, {"level": a["level"], "flagged": a["flagged"]})

    def submit_pvt(self, aid: str, rts_ms: list[float], anticipations: int = 0, misses: int = 0,
                   duration_s: float | None = None, trials: int | None = None) -> dict:
        if aid not in self.by_id:
            return {"ok": False, "error": "unknown astronaut"}
        res = score_pvt(rts_ms, anticipations)
        stats = pvt_stats(rts_ms, anticipations, misses)
        run = {"id": len(self.pvt_runs.setdefault(aid, [])) + 1, "t": self.t,
               "mission_day": round(self.mission.status(self.t)["mission_day"], 2), "duration_s": duration_s,
               "trials": trials, "valid": bool(res.get("valid")), "stats": stats, "score": res, "source": "live (browser)"}
        prev = [r for r in self.pvt_runs[aid] if r["valid"]]
        if prev:
            run["previous"] = {"mean_rt_ms": prev[-1]["stats"]["mean_rt_ms"], "lapses": prev[-1]["stats"]["lapses"],
                               "mission_day": prev[-1]["mission_day"]}
        self.pvt_runs[aid].append(run)
        self.twins[aid].add_event(self.t, "pvt", f"Reaction-time test: mean {stats['mean_rt_ms']} ms, "
                                  f"{stats['lapses']} lapses ({'scored' if run['valid'] else 'too short to score'})", 0)
        if not res.get("valid"):
            return {"ok": False, "result": res, "run": run}
        bp = self.behavior[aid]
        before = bp.assess()["level"]
        a = bp.add(BehavioralRecord(self.mission.status(self.t)["mission_day"], res, None, None, "live"))
        self._behavioral_change(aid, self.t, before, a)
        run["assessment"] = {"level": a["level"], "label": a["label"]}
        return {"ok": True, "result": res, "assessment": a, "run": run}

    def submit_checkin(self, aid: str, checkin: dict) -> dict:
        bp = self.behavior[aid]
        before = bp.assess()["level"]
        a = bp.add(BehavioralRecord(self.mission.status(self.t)["mission_day"], None, checkin, None, "live"))
        self._behavioral_change(aid, self.t, before, a)
        return {"ok": True, "assessment": a}

    def behavioral_view(self, aid: str) -> dict:
        bp = self.behavior[aid]
        return {"assessment": bp.assess(), "series": bp.series(), "strain_active": self._strain(aid) > 0}

    # ------------------------------------------------------------------ model monitoring & integrity
    def _monitor(self, an, feats) -> None:
        if an is not None:
            self._anom_hist.append(an >= 0.995)
        if self._ranges:
            ood = sum(1 for f, (lo, hi) in self._ranges.items() if not (lo - 1e-9 <= feats.get(f, 0.0) <= hi + 1e-9))
            self._ood_hist.append(ood / len(self._ranges))

    def system_health(self) -> dict:
        root = Path(__file__).resolve().parents[1]
        card_p = root / "models" / "model_card.json"
        card = json.loads(card_p.read_text()) if card_p.exists() else {}
        files = {}
        for name, want in card.get("sha256", {}).items():
            f = root / "models" / name
            files[name] = {"present": f.exists(),
                           "hash_ok": f.exists() and hashlib.sha256(f.read_bytes()).hexdigest() == want}
        kb = root / "knowledge_base" / "protocols.json"
        rate = float(np.mean(self._anom_hist)) if self._anom_hist else None
        ood = float(np.mean(self._ood_hist)) if self._ood_hist else None
        return {
            "models": {"anomaly_ready": self.anomaly.ready, "forecaster_ready": self.forecaster.ready,
                       "files": files, "trained": card.get("forecaster", {}).get("trained")},
            "model_monitoring": {
                "anomaly_flag_rate_24h": None if rate is None else round(rate, 4),
                "anomaly_expected_rate": 0.005,
                "anomaly_drift_warning": rate is not None and len(self._anom_hist) > 600 and rate > 0.03,
                "feature_out_of_range_frac_24h": None if ood is None else round(ood, 4),
                "note": "Flag rate far above the nominal 0.5% while crew are well suggests the population has "
                        "drifted from training data (e.g., spaceflight adaptation) - retrain/recalibrate."},
            "integrity": {"store": self.store.verify() if self.store else "persistence off",
                          "store_rows": self.store.counts() if self.store else None,
                          "knowledge_base_sha256": hashlib.sha256(kb.read_bytes()).hexdigest()[:16],
                          "kb_status": self.kb.meta["status"]},
            "edge": {"components_onboard": ["acquisition", "signal processing", "digital twin", "anomaly model",
                                            "forecaster", "classifier", "protocol retrieval", "comm queue", "store"],
                     "earth_side": ["flight-surgeon review", "model retraining", "KB approval/updates"]},
        }

    # ------------------------------------------------------------------ cabin environment
    def _cabin_logic(self, t: float) -> None:
        ca = self.cabin.assess({a: (self.last[a] or {}).get("state") for a in self.last})
        self.cabin_state = ca
        # SIMULATED symptom reports: some crew report headache once ppCO2 is clearly elevated
        if ca.get("co2_1h", 0) > 3.5:
            for p in self.crew:
                if p.id not in self._headache_reported and self._brng.random() < 0.004:
                    self._headache_reported.add(p.id)
                    self.clinical[p.id].report_symptoms(t, ["headache"])
                    self._log(f"[SIMULATED] {p.name} reports headache", 1)
        env = self.active.get("CABIN")
        lvl = ca.get("level", 0)
        if lvl >= 2 and env is None:
            inc_id = next(self._inc_ids)
            self.active["CABIN"] = inc_id
            p = self.kb.by_id["ENV-01"]
            text = (ca.get("attribution") or {}).get("text") or "; ".join(ca["findings"])
            self.incidents[inc_id] = {
                "id": inc_id, "astronaut_id": "CABIN", "opened": t, "closed": None, "level": 2, "peak_level": 2,
                "acknowledged": False, "history": [(t, 2)], "_calm": 0,
                "report": {"event": "EVENT: CABIN ENVIRONMENT ABNORMALITY (CO2)", "level": 2,
                           "level_label": "Environmental - crew + vehicle action",
                           "reasons": ca["findings"] + ([ca["attribution"]["text"]] if ca.get("attribution") else []),
                           "recommended_protocols": [{"id": p["id"], "title": p["title"], "steps": p["assessment_steps"],
                                                      "escalation": p["escalation_criteria"], "source": p["source"],
                                                      "approval": p["approval"]}],
                           "crew_notification": "ALL CREW (caution & warning)", "earth_communication_priority": "P2 priority",
                           "disclaimer": "Cabin sensors are SIMULATED. Limits from NASA-STD-3001 Vol 2."}}
            for tw in self.twins.values():
                tw.add_event(t, "environment", f"#{inc_id} Cabin CO2 event - {text[:90]}", 2)
            self.comms.enqueue(2, t, "environment", f"#{inc_id} Cabin ppCO2 {ca['co2_1h']} mmHg (1-h mean); crew-wide response")
            self._log(f"Cabin: CO2 event (incident #{inc_id}) - {text[:120]}", 2)
        elif env is not None:
            inc = self.incidents[env]
            inc["report"]["reasons"] = ca["findings"] + ([ca["attribution"]["text"]] if ca.get("attribution") else [])
            inc["_calm"] = inc.get("_calm", 0) + 1 if lvl == 0 else 0
            if inc["_calm"] >= 15:
                inc["closed"], inc["level"] = t, 0
                del self.active["CABIN"]
                self.comms.enqueue(3, t, "environment", f"#{env} cabin environment back within limits")
                self._log(f"Cabin: environment nominal again (incident #{env} closed)", 0)

    # ------------------------------------------------------------------ clinical log
    def submit_symptoms(self, aid: str, items: list[str]) -> dict:
        rec = self.clinical[aid].report_symptoms(self.t, items)
        if rec["symptoms"]:
            self.twins[aid].add_event(self.t, "symptoms", "Reported: " + ", ".join(rec["symptoms"]).replace("_", " "), 1)
            self._log(f"{self.by_id[aid].name} reported symptoms: {', '.join(rec['symptoms'])}", 0)
        return {"ok": True, "record": rec}

    def submit_labs(self, aid: str, values: dict) -> dict:
        a = self.clinical[aid].add_labs(self.t, values)
        if a["flags"]:
            self.twins[aid].add_event(self.t, "labs", "Lab flags: " + "; ".join(a["flags"])[:120], 1)
            self.comms.enqueue(3, self.t, "labs", f"{self.by_id[aid].name}: lab results with flags (CMO review)", aid)
        return {"ok": True, "assessment": a}
