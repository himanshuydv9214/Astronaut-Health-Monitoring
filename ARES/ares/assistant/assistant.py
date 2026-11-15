"""Onboard medical knowledge assistant - retrieval only, no text generation.

Why no LLM? An onboard assistant that can invent a medical instruction is a
hazard; a generative model also needs compute that a spacecraft may not have
(NASA's EIMO workshop notes flagged both points). ARES therefore routes each
question to one of a fixed set of deterministic answerers and only ever
returns (a) data computed by ARES itself or (b) knowledge-base entries
VERBATIM, each with its source and approval status. If nothing matches, it
says so and points to the CMO / flight surgeon.

A generative layer (e.g., an offline small LLM used only to phrase the
retrieved, cited content) is a possible extension; it must never be the
source of medical content. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ares.config import PARAMS

DISCLAIMER = ("Retrieval-only decision support from a DEMO knowledge base (unapproved entries). "
              "Not medical advice; the CMO / flight surgeon decides.")

INTENTS = [
    ("explain", r"\b(why|explain|reason|alert|alarm|flag|level|triggered)\b"),
    ("history", r"\b(history|summary|summari[sz]e|timeline|trend|baseline|drift|since)\b"),
    ("inventory", r"\b(supply|supplies|inventory|equipment|kit|have on ?board|stock|available|oxygen supply|aed|cuff)\b"),
    ("report", r"\b(report|incident|status report|sitrep)\b"),
    ("radiation", r"\b(radiation|dose|dosimeter|spe|solar|shelter|msv)\b"),
    ("behavioral", r"\b(pvt|vigilance|fatigue|mood|stress|sleep|behaviou?ral|readiness|tired)\b"),
]


class Assistant:
    def __init__(self, engine):
        self.e = engine
        items = engine.inventory["items"]
        self.inv_docs = [f"{i['item']} {i['location']} {i['notes']}" for i in items]
        self.inv_vec = TfidfVectorizer(stop_words="english").fit(self.inv_docs)
        self.inv_mat = self.inv_vec.transform(self.inv_docs)

    def ask(self, question: str, astronaut_id: str | None = None) -> dict:
        q = (question or "").strip()
        aid = astronaut_id if astronaut_id in self.e.by_id else self.e.crew[0].id
        for name in self.e.by_id.values():   # "why is Tanaka flagged?" -> that astronaut
            if name.name.split()[-1].lower() in q.lower():
                aid = name.id
        intents = [n for n, rx in INTENTS if re.search(rx, q.lower())] or ["protocol"]
        sections = []
        for it in intents[:2]:
            sections.append(getattr(self, f"_{it}")(q, aid))
        if "protocol" not in intents:
            prot = self._protocol(q, aid, quiet=True)
            if prot["items"]:
                sections.append(prot)
        return {"question": q, "astronaut_id": aid, "intents": intents, "sections": sections,
                "generated_text": False, "disclaimer": DISCLAIMER}

    # ---------------------------------------------------------------- answerers
    def _explain(self, q, aid):
        L = self.e.last[aid]
        cls = L["cls"]
        st = L["state"]
        items = [f"Current level L{cls['level']} - {cls['label']} (confidence {cls['confidence_label']} {cls['confidence']:.2f})"]
        items += cls["reasons"] or ["No sustained deviation from this astronaut's personal baselines."]
        ex = self.e.astronaut_detail(aid)["explanation"]
        items += ex["baseline_text"][:4] + ex["significant_changes"][:3]
        if ex["influencing_parameters"]:
            items.append("Top forecaster attributions (SHAP): " + ", ".join(
                f"{p['feature']} {p['contribution']:+.2f}" for p in ex["influencing_parameters"][:4]))
        if ex["missing"]:
            items.append("Missing / unreliable: " + "; ".join(ex["missing"][:4]))
        items.append(f"Context: {st['context']}; sensors {st['sensor_health']}")
        return {"type": "explanation", "title": f"Why {self.e.by_id[aid].name} is at L{cls['level']}",
                "items": items, "source": "ARES classifier + digital twin (computed onboard)"}

    def _history(self, q, aid):
        tw = self.e.twins[aid]
        drift = tw.drift_summary()
        items = [f"{PARAMS[k].label}: resting baseline drift {v['drift']:+.2f} {v['unit']} since baseline freeze"
                 for k, v in drift.items() if abs(v["drift"]) > 0.01]
        incs = [i for i in self.e.incidents.values() if i["astronaut_id"] == aid]
        items.append(f"Incidents this session: {len(incs)}" + (
            " (" + ", ".join(f"#{i['id']} peak L{i['peak_level']}" for i in incs[-5:]) + ")" if incs else ""))
        items += [f"t+{e['t'] - self.e.baseline_end:.0f} min: {e['text']}" for e in tw.timeline[-6:][::-1]]
        p = self.e.by_id[aid]
        items.append("Medical history on file: " + "; ".join(p.medical_history or ["none"]))
        return {"type": "history", "title": f"Health summary - {p.name}", "items": items,
                "source": "Digital twin timeline (computed onboard; crew are fictional)"}

    def _inventory(self, q, aid):
        sims = cosine_similarity(self.inv_vec.transform([q]), self.inv_mat)[0]
        items = self.e.inventory["items"]
        order = [i for i in sims.argsort()[::-1] if sims[i] > 0.05][:5] or range(len(items))
        return {"type": "inventory", "title": "Onboard medical resources",
                "items": [f"{items[i]['item']} x{items[i]['qty']} - {items[i]['location']}"
                          + (f" ({items[i]['notes']})" if items[i]["notes"] else "") for i in order],
                "source": "knowledge_base/medical_inventory.json - " + self.e.inventory["_meta"]["status"]}

    def _report(self, q, aid):
        inc_id = self.e.active.get(aid)
        if inc_id is None:
            return {"type": "report", "title": "No active incident", "items": [
                f"{self.e.by_id[aid].name} has no open incident."], "source": "ARES incident log"}
        r = self.e.incidents[inc_id]["report"] or {}
        items = [r.get("event", ""), f"Level: L{r.get('level')} {r.get('level_label')}",
                 f"Crew notification: {r.get('crew_notification')}",
                 f"Earth priority: {r.get('earth_communication_priority')}",
                 (r.get("mission_context") or {}).get("guidance", "")]
        items += [f"{m['parameter']}: {m['value']} {m['unit']} (usual {m['personal_expected']}, z={m['z']})"
                  for m in r.get("abnormal_measurements", [])]
        return {"type": "report", "title": f"Incident #{inc_id} structured report", "items": items,
                "source": "ARES emergency report (template-based)"}

    def _radiation(self, q, aid):
        d = self.e.dose[aid].snapshot(self.e.mission.status(self.e.t)["days_to_mars"],
                                       self.e.mission.status(self.e.t)["gcr_model_rate_msv_day"])
        items = [f"Measured this mission: {d['measured_mission_msv']} mSv (simulated dosimeter)",
                 f"Modelled GCR this mission: {d['modelled_mission_msv']} mSv (MSL/RAD published rates)",
                 f"Career total: {d['career_total_msv']} mSv = {d['pct_career_limit']}% of the NASA-STD-3001 "
                 f"{d['career_limit_msv']:.0f} mSv limit", f"Projected at Mars arrival: {d['projected_at_mars_arrival_msv']} mSv",
                 "Individual biological (cancer) risk: not computed - short-term dosimetry cannot predict it."]
        if self.e.spe.active:
            items.insert(0, "SOLAR PARTICLE EVENT ACTIVE - storm shelter " + ("occupied" if self.e.shelter else "advised"))
        return {"type": "radiation", "title": f"Radiation - {self.e.by_id[aid].name}", "items": items,
                "source": "ARES dose tracker; Zeitlin et al. Science 2013; NASA-STD-3001 Vol 1"}

    def _behavioral(self, q, aid):
        a = self.e.behavior[aid].assess()
        items = [f"Readiness: {a['label']}"] + [d["text"] for d in a["domains"].values()]
        items.append(a["note"])
        return {"type": "behavioral", "title": f"Behavioral readiness - {self.e.by_id[aid].name} (private: astronaut + CMO)",
                "items": items, "source": "PVT-B (Basner 2011; ISS Reaction Self Test), Samn-Perelli, actigraphy"}

    def _protocol(self, q, aid, quiet=False):
        hits = self.e.kb.search(q, k=3)
        if not hits and not quiet:
            return {"type": "protocol", "title": "No matching protocol",
                    "items": ["No knowledge-base entry matched this question. ARES will not improvise medical "
                              "instructions - consult the CMO / flight surgeon (queue a P2 message if needed)."],
                    "source": "knowledge_base/protocols.json"}
        return {"type": "protocol", "title": "Retrieved protocols (verbatim)",
                "items": [{"id": p["id"], "title": p["title"], "score": round(s, 3), "steps": p["assessment_steps"],
                           "escalation": p["escalation_criteria"], "citation": self.e.kb.cite(p)} for p, s in hits],
                "source": "knowledge_base/protocols.json (" + self.e.kb.meta["status"] + ")"}
