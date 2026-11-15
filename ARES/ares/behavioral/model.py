"""Behavioral & cognitive readiness - personal-baseline assessment.

The official 2026 Space Apps challenge asks for monitoring of physical AND
mental health. Physiology alone cannot see vigilance decline, mood change or
accumulating strain, so ARES adds a behavioral channel built from instruments
that NASA actually flies or that are validated in operational settings:

  * PVT-B vigilance test (objective)      - ares.behavioral.pvt
  * Samn-Perelli 7-point fatigue scale    - aviation fatigue standard
    (1 = fully alert ... 7 = completely exhausted; Samn & Perelli, USAF 1982)
  * Visual-analog self-ratings 0-10       - mood, stress, workload, sleep quality
    (the ISS Reaction Self Test used VAS ratings of behavioral states)
  * Objective sleep from actigraphy       - from the digital twin

Design decisions
----------------
* Output is a READINESS status (Nominal / Watch / Support suggested), kept
  separate from the 0-3 physiological emergency scale. Behavioral change is
  not a medical emergency and must not be presented as a diagnosis.
* Personal baselines: each person's own first tests define "usual". Practice
  effects exist on the PVT; the first test is treated as familiarisation.
* Privacy: behavioral results are visible to the astronaut and the crew
  medical officer only, are never broadcast crew-wide, and Earth reports carry
  only the readiness category (no free-text, no scores) unless the astronaut
  chooses to share more.
* Thresholds below are ENGINEERING CHOICES for the prototype; the Samn-Perelli
  >= 5 "fatigue affects performance" point follows common aviation use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SP_WATCH = 5          # Samn-Perelli >= 5: "moderately tired, let down" -> performance affected
SP_SUPPORT = 6
SPEED_Z_WATCH = -2.0  # response speed this far below personal baseline (2 consecutive tests)
SPEED_Z_SINGLE = -3.0  # ...or this far on a single test
LAPSE_EXCESS_WATCH = 3
SLEEP_DEBT_WATCH_H = 4.0      # cumulative 7-day debt vs personal sleep need
VAS_DROP_WATCH = 3.0          # mood/sleep-quality drop vs personal baseline (0-10 scale)
STRESS_WATCH = 7.0
PERSIST_DAYS_SUPPORT = 3

READINESS = {0: "Nominal", 1: "Watch", 2: "Support suggested"}


@dataclass
class BehavioralRecord:
    day: float
    pvt: dict | None = None
    checkin: dict | None = None      # {samn_perelli, mood, stress, workload, sleep_quality}
    sleep_h: float | None = None
    source: str = "simulated"        # 'simulated' or 'live' (taken in the dashboard)


@dataclass
class BehavioralProfile:
    astronaut_id: str
    sleep_need_h: float = 8.0
    records: list[BehavioralRecord] = field(default_factory=list)
    status_history: list[tuple[float, int]] = field(default_factory=list)

    # ---------------------------------------------------------------- data
    def add(self, rec: BehavioralRecord) -> dict:
        self.records.append(rec)
        self.records = self.records[-120:]
        a = self.assess()
        self.status_history.append((rec.day, a["level"]))
        return a

    def _valid_pvts(self) -> list[tuple[float, dict]]:
        return [(r.day, r.pvt) for r in self.records if r.pvt and r.pvt.get("valid")]

    def _baseline(self) -> dict:
        """Personal baseline from the 2nd-6th valid tests (1st = familiarisation)."""
        pv = [p for _, p in self._valid_pvts()]
        base = pv[1:6] if len(pv) >= 3 else pv
        ci = [r.checkin for r in self.records if r.checkin][:5]
        out = {"n_pvt": len(base), "n_checkin": len(ci)}
        if base:
            sp = np.array([p["response_speed"] for p in base])
            # population-informed floor on spread so 2-3 tests do not give absurdly tight bands
            out["speed_mean"] = float(sp.mean())
            out["speed_sd"] = float(max(sp.std(ddof=1) if len(sp) > 1 else 0.0, 0.18))
            out["lapses_mean"] = float(np.mean([p["lapses"] for p in base]))
        for k in ("mood", "sleep_quality", "stress"):
            vals = [c[k] for c in ci if c.get(k) is not None]
            if vals:
                out[f"{k}_mean"] = float(np.mean(vals))
        return out

    def sleep_debt_7d(self) -> float | None:
        sl = [r.sleep_h for r in self.records[-7:] if r.sleep_h is not None]
        if not sl:
            return None
        return float(sum(max(0.0, self.sleep_need_h - s) for s in sl))

    # ---------------------------------------------------------------- assessment
    def assess(self) -> dict:
        b = self._baseline()
        domains: dict[str, dict] = {}
        last_pvt = next((r for r in reversed(self.records) if r.pvt and r.pvt.get("valid")), None)
        last_ci = next((r for r in reversed(self.records) if r.checkin), None)

        if last_pvt and "speed_mean" in b and b["n_pvt"] >= 2:
            p = last_pvt.pvt

            def dev(pp):
                return ((pp["response_speed"] - b["speed_mean"]) / b["speed_sd"], pp["lapses"] - b["lapses_mean"])
            z, excess = dev(p)
            bad = z <= SPEED_Z_WATCH or excess >= LAPSE_EXCESS_WATCH
            # One slow test is not a decline (PVT test-retest variability): flag when two consecutive
            # tests are impaired, or a single test is markedly impaired (z <= -3).
            prev = [pp for _, pp in self._valid_pvts()][-2:-1]
            prev_bad = bool(prev) and (dev(prev[0])[0] <= SPEED_Z_WATCH or dev(prev[0])[1] >= LAPSE_EXCESS_WATCH)
            flag = (bad and prev_bad) or z <= SPEED_Z_SINGLE
            domains["vigilance"] = {"flag": bool(flag), "speed": p["response_speed"], "speed_z": round(z, 2),
                                    "lapses": p["lapses"], "lapse_excess": round(excess, 1),
                                    "text": f"PVT-B speed {p['response_speed']:.2f}/s (z={z:+.1f} vs own baseline), "
                                            f"{p['lapses']} lapses ({excess:+.0f} vs usual)"}
        if last_ci:
            c = last_ci.checkin
            sp = c.get("samn_perelli")
            if sp is not None:
                domains["fatigue"] = {"flag": sp >= SP_WATCH, "samn_perelli": sp,
                                      "text": f"Samn-Perelli fatigue {sp}/7"}
            drops = []
            for k in ("mood", "sleep_quality"):
                if c.get(k) is not None and f"{k}_mean" in b and b[f"{k}_mean"] - c[k] >= VAS_DROP_WATCH:
                    drops.append(f"{k.replace('_', ' ')} {c[k]:.0f}/10 (usual {b[f'{k}_mean']:.0f})")
            stress = c.get("stress")
            if stress is not None and stress >= STRESS_WATCH:
                drops.append(f"stress {stress:.0f}/10")
            if c.get("mood") is not None or stress is not None:
                domains["wellbeing"] = {"flag": bool(drops), "text": "; ".join(drops) or "self-ratings within usual range"}
        debt = self.sleep_debt_7d()
        if debt is not None:
            domains["sleep"] = {"flag": debt >= SLEEP_DEBT_WATCH_H, "debt_7d_h": round(debt, 1),
                                "text": f"7-day sleep debt {debt:.1f} h vs {self.sleep_need_h:.0f} h need (actigraphy)"}

        flagged = [k for k, d in domains.items() if d["flag"]]
        level = 1 if flagged else 0
        sp = domains.get("fatigue", {}).get("samn_perelli")
        if len(flagged) >= 2 or (sp is not None and sp >= SP_SUPPORT):
            level = 2
        recent = [lv for _, lv in self.status_history[-PERSIST_DAYS_SUPPORT:]]
        if level == 1 and len(recent) >= PERSIST_DAYS_SUPPORT and all(lv >= 1 for lv in recent):
            level = 2
            flagged.append(f"persisting >= {PERSIST_DAYS_SUPPORT} days")
        return {
            "level": level, "label": READINESS[level], "domains": domains, "flagged": flagged,
            "baseline": b, "n_records": len(self.records),
            "visibility": "Astronaut + CMO only (private behavioral channel)",
            "earth_summary": f"Behavioral readiness: {READINESS[level]}",   # no scores/free text leave the vehicle
            "note": "Readiness indicator from validated instruments vs personal baseline. Not a diagnosis.",
        }

    def series(self) -> dict:
        pv = self._valid_pvts()
        return {
            "pvt_day": [round(d, 2) for d, _ in pv], "speed": [p["response_speed"] for _, p in pv],
            "lapses": [p["lapses"] for _, p in pv],
            "ci_day": [round(r.day, 2) for r in self.records if r.checkin],
            "samn_perelli": [r.checkin.get("samn_perelli") for r in self.records if r.checkin],
            "mood": [r.checkin.get("mood") for r in self.records if r.checkin],
            "stress": [r.checkin.get("stress") for r in self.records if r.checkin],
            "sleep_day": [round(r.day, 2) for r in self.records if r.sleep_h is not None],
            "sleep_h": [round(r.sleep_h, 2) for r in self.records if r.sleep_h is not None],
            "sources": [r.source for r in self.records],
        }
