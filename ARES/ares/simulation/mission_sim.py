"""Interactive Mars-mission simulation controller.

Drives the REAL engine: every step injects a physiological scenario, changes the Earth link or clears scenarios,
and the normal ARES pipeline (twin -> classifier -> ML -> incidents -> 3D mapping -> comm queue) reacts to it.
Nothing here writes numbers to the screen directly. All data produced are SIMULATED and labelled as such.

States: idle -> running <-> paused -> stopped | completed ; reset rebuilds a fresh engine (baseline re-acquired).
"""

from __future__ import annotations

import threading
import time

SCRIPTS = {
    "normal": {
        "title": "Normal mission", "speed": 10, "duration_min": 480,
        "summary": "A quiet day in cruise. Vital signs follow sleep, work and exercise; ARES should stay calm.",
        "watch": "Crew cards stay green; resting values stay inside each person's normal band; no incidents.",
        "steps": [(0, "note", None, "Nominal cruise day - no problems injected")],
    },
    "gradual_cardiovascular": {
        "title": "Gradual cardiovascular changes", "speed": 20, "duration_min": 720,
        "summary": "Resting heart rate slowly rises and blood pressure sags over ~8 hours (deconditioning pattern).",
        "watch": "'Gradual changes from normal' moves from Stable to Watch to Gradual change; heart glows yellow.",
        "steps": [(2, "inject", "gradual_cardiovascular", "Slow cardiovascular change begins"),
                  (240, "note", None, "Check 'Gradual changes from normal' on the crew health page")],
    },
    "respiratory": {
        "title": "Respiratory abnormality", "speed": 4, "duration_min": 150,
        "summary": "Breathing rate climbs and blood oxygen dips over ~30 minutes.",
        "watch": "Lungs light up on the body, an incident opens, protocol RESP-01 is retrieved.",
        "steps": [(2, "inject", "respiratory", "Breathing problem begins")],
    },
    "severe_fatigue": {
        "title": "Severe fatigue", "speed": 30, "duration_min": 3 * 1440,
        "summary": "Three days of shortened sleep plus workload strain. Reaction-time tests slow down.",
        "watch": "Sleep falls, resting heart rate drifts up, the alertness status changes to Watch.",
        "steps": [(2, "inject", "sleep_deprivation", "Sleep opportunity cut by 3.5 h per night"),
                  (5, "inject", "behavioral_strain", "Workload and isolation strain added")],
    },
    "multiple": {
        "title": "Multiple simultaneous problems", "speed": 4, "duration_min": 200,
        "summary": "One astronaut develops a fever-like multi-system problem, another an irregular heart rhythm, "
                   "then cabin CO2 rises for everyone.",
        "watch": "Several incidents at once, sorted by severity; CO2 is attributed to the cabin, not to 4 illnesses.",
        "steps": [(2, "inject", "multi_system", "Multi-system problem (target astronaut)"),
                  (10, "inject_other", "cardiac_arrhythmia", "Irregular heart rhythm (second astronaut)"),
                  (25, "inject", "co2_buildup", "Cabin CO2 removal degrades (whole crew)")],
    },
    "sensor_failure": {
        "title": "Sensor failure", "speed": 4, "duration_min": 180,
        "summary": "The finger oxygen sensor flatlines, then an ECG lead falls off. The astronaut is actually fine.",
        "watch": "ARES flags the SENSOR, not the astronaut; the body region turns grey, not red.",
        "steps": [(2, "inject", "sensor_malfunction", "Oxygen sensor flatline, then ECG lead-off")],
    },
    "blackout_emergency": {
        "title": "Emergency during Earth blackout", "speed": 3, "duration_min": 140,
        "summary": "The Earth link is lost (solar conjunction) and an oxygen emergency starts. ARES must act alone.",
        "watch": "Emergency handled onboard; reports wait in the queue and send when the link returns at T+90.",
        "steps": [(0, "comm", "blackout", "Earth link lost (blackout)"),
                  (3, "inject", "blackout_emergency", "Oxygen emergency during blackout"),
                  (90, "comm", None, "Earth link restored - queued reports start sending")],
    },
    "recovery": {
        "title": "Recovery after an emergency", "speed": 4, "duration_min": 240,
        "summary": "A moderate low-oxygen episode that resolves on its own after ~45 minutes.",
        "watch": "Alert level rises, then steps down with hysteresis; post-event monitoring follows.",
        "steps": [(2, "inject", "recovery", "Low-oxygen episode begins"),
                  (60, "note", None, "Physiology recovering - watch the alert level step down")],
    },
}


class MissionSimulation:
    def __init__(self, runtime):
        self.rt = runtime
        self.state = "idle"
        self.key: str | None = None
        self.target: str | None = None
        self.t_start: float | None = None
        self.next_step = 0
        self.events: list[dict] = []
        self.error: str | None = None
        self.reset_started: float | None = None

    # ---------------------------------------------------------------- helpers
    def _ev(self, text: str):
        e = self.rt.engine
        self.events.append({"t": e.t, "elapsed_min": None if self.t_start is None else round(e.t - self.t_start, 1),
                            "text": text})
        self.events = self.events[-80:]
        e._log(f"[SIMULATION] {text}")

    def _do(self, step):
        e = self.rt.engine
        _, action, arg, text = step
        if action == "inject":
            e.trigger(arg, self.target)
        elif action == "inject_other":
            other = next((c.id for c in e.crew if c.id != self.target), self.target)
            e.trigger(arg, other)
            text += f" -> {e.by_id[other].name}"
        elif action == "comm":
            e.set_comm_override(arg)
        elif action == "clear":
            e.clear_scenarios()
        self._ev(text)

    # ---------------------------------------------------------------- controls (call under runtime lock)
    def start(self, key: str, target: str | None, speed: float | None) -> dict:
        if key not in SCRIPTS:
            raise KeyError(key)
        if self.state == "resetting":
            raise RuntimeError("reset in progress")
        e = self.rt.engine
        if self.state in ("running", "paused", "completed"):
            self._ev(f"Previous run '{SCRIPTS[self.key]['title']}' stopped" if self.key else "Previous run stopped")
        e.clear_scenarios()
        e.set_comm_override(None)
        self.key, self.target = key, target if target in e.by_id else e.crew[0].id
        self.t_start, self.next_step, self.state, self.error = e.t, 0, "running", None
        self.rt.speed = float(speed or SCRIPTS[key]["speed"])
        self.rt.paused = False
        self._ev(f"Simulation started: {SCRIPTS[key]['title']} (target {e.by_id[self.target].name}, "
                 f"{self.rt.speed:g} mission-min/s)")
        self.update()
        return self.status()

    def pause(self):
        if self.state == "running":
            self.rt.paused, self.state = True, "paused"
            self._ev("Simulation paused - mission clock and data generation stopped")

    def resume(self):
        if self.state == "paused":
            self.rt.paused, self.state = False, "running"
            self._ev("Simulation resumed")

    def stop(self):
        if self.state in ("running", "paused", "completed"):
            e = self.rt.engine
            e.clear_scenarios()
            e.set_comm_override(None)
            self.rt.paused = True
            self.state = "stopped"
            self._ev("Simulation stopped - scenarios cleared, clock paused (Resume clock or Start a new run)")

    def update(self):
        """Called by the clock thread after every engine tick (under the runtime lock)."""
        if self.state != "running" or self.key is None:
            return
        e = self.rt.engine
        sc = SCRIPTS[self.key]
        el = e.t - self.t_start
        while self.next_step < len(sc["steps"]) and el >= sc["steps"][self.next_step][0]:
            try:
                self._do(sc["steps"][self.next_step])
            except Exception as ex:  # noqa: BLE001 - never let a script step stop the mission clock
                self.error = f"{type(ex).__name__}: {ex}"
                self._ev(f"Step failed: {self.error}")
            self.next_step += 1
        if el >= sc["duration_min"]:
            self.state = "completed"
            self.rt.speed = min(self.rt.speed, 2.0)      # don't let the mission race on unattended
            self._ev(f"Scenario '{sc['title']}' completed after {el:.0f} mission minutes - mission continues; "
                     "clock back to 2x; press Stop or start another scenario")

    # ---------------------------------------------------------------- reset (rebuild engine off-lock)
    def reset(self):
        if self.state == "resetting":
            return
        self.state, self.reset_started = "resetting", time.time()
        self.rt.paused = True

        def work():
            from ares.assistant.assistant import Assistant
            from ares.engine import AresEngine
            try:
                eng = AresEngine(persist=True)
                with self.rt.lock:
                    if hasattr(self.rt, "save_state"):
                        self.rt.save_state()            # archive this run's incidents before the engine is replaced
                    self.rt.engine = eng
                    self.rt.gen = getattr(self.rt, "gen", 0) + 1
                    self.rt.assistant = Assistant(eng)
                    if hasattr(self.rt, "_restore_history"):
                        self.rt._restore_history()
                    self.key = self.target = self.t_start = None
                    self.next_step, self.events, self.state = 0, [], "idle"
                    self.rt.speed, self.rt.paused = 2.0, False
                    eng._log("[SIMULATION] Reset complete - fresh crew baselines, mission day 200, nominal state")
            except Exception as ex:  # noqa: BLE001
                self.state, self.error = "idle", f"reset failed: {ex}"
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- view
    def status(self) -> dict:
        e = self.rt.engine
        sc = SCRIPTS.get(self.key) if self.key else None
        el = None if self.t_start is None else round(e.t - self.t_start, 1)
        steps = []
        if sc:
            for i, (at, action, arg, text) in enumerate(sc["steps"]):
                steps.append({"at_min": at, "text": text, "done": i < self.next_step})
        return {
            "state": self.state, "scenario": self.key, "title": sc["title"] if sc else None,
            "target": self.target, "target_name": e.by_id[self.target].name if self.target in e.by_id else None,
            "elapsed_min": el, "duration_min": sc["duration_min"] if sc else None,
            "progress": None if not sc or el is None else round(min(1.0, el / sc["duration_min"]), 3),
            "speed": self.rt.speed, "clock_paused": self.rt.paused, "steps": steps, "events": self.events[::-1][:40],
            "error": self.error, "simulated": True,
            "reset_seconds": None if self.state != "resetting" else round(time.time() - (self.reset_started or 0), 1),
            "scenarios": [{"key": k, "title": v["title"], "summary": v["summary"], "watch": v["watch"],
                           "speed": v["speed"], "duration_min": v["duration_min"]} for k, v in SCRIPTS.items()],
        }
