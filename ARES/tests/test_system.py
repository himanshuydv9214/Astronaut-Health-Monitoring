"""System-level tests: classifier rules, comms, behavioral, cabin, storage, assistant, API."""
import numpy as np
import pytest

from ares.behavioral.model import BehavioralProfile, BehavioralRecord
from ares.behavioral.pvt import score_pvt
from ares.emergency.classifier import EmergencyClassifier
from ares.environment.cabin import CabinMonitor
from ares.mission.comms import CommQueue
from ares.mission.context import HohmannMission, MissionContext


def _state(z: dict, values: dict, ctx="rest", age=None, faults=None):
    keys = ["hr", "hrv_rmssd", "spo2", "rr", "sbp", "dbp", "temp"]
    return {"z": {k: z.get(k, 0.0) for k in keys}, "values": {k: values.get(k, 1.0) for k in keys},
            "expected": {k: values.get(k, 1.0) for k in keys}, "context": ctx, "faults": faults or [],
            "quality": {k: 1.0 for k in keys}, "uncertainty": {k: 0.05 for k in keys},
            "slope_h": {k: 0.0 for k in keys}, "slope_sd_h": {k: 1.0 for k in keys},
            "age_min": age or {k: 0 for k in keys}}


NORMAL = {"hr": 60, "hrv_rmssd": 40, "spo2": 97, "rr": 14, "sbp": 115, "dbp": 75, "temp": 36.8}


# ----------------------------------------------------------------- classifier
def test_single_cuff_reading_never_escalates_to_emergency():
    c = EmergencyClassifier()
    v = dict(NORMAL, sbp=82)                       # one low reading, held for 14 more minutes
    for i in range(15):
        age = {k: 0 for k in NORMAL} | {"sbp": i, "dbp": i}
        out = c.classify(_state({"sbp": -2.5}, v, age=age))
    assert out.level <= 1
    assert any("repeat" in r.lower() for r in out.verify_readings)


def test_population_limit_without_personal_corroboration_is_observation_only():
    c = EmergencyClassifier()
    v = dict(NORMAL, rr=7.5)                       # below generic limit (8) but usual for this person
    for _ in range(30):
        out = c.classify(_state({"rr": -0.3}, v, ctx="sleep"))
    assert out.level == 1


def test_sustained_desaturation_escalates_critical():
    c = EmergencyClassifier()
    v = dict(NORMAL, spo2=83, hr=95, rr=24)
    for _ in range(5):
        out = c.classify(_state({"spo2": -12, "hr": 5, "rr": 5}, v))
    assert out.level == 3


def test_sensor_fault_needs_persistence_and_never_medical():
    c = EmergencyClassifier()
    out = c.classify(_state({}, NORMAL, faults=["spo2:flatline"]))
    assert out.level == 0                           # one glitchy minute is not an event
    for _ in range(5):
        out = c.classify(_state({}, NORMAL, faults=["spo2:flatline"]))
    assert out.level == 1 and out.sensor_alert


def test_hysteresis_holds_then_clears():
    c = EmergencyClassifier()
    bad = dict(NORMAL, spo2=83, hr=95, rr=24)
    for _ in range(5):
        c.classify(_state({"spo2": -12, "hr": 5, "rr": 5}, bad))
    levels = [c.classify(_state({}, NORMAL)).level for _ in range(20)]
    assert levels[0] == 3 and levels[-1] == 0


# ----------------------------------------------------------------- mission & comms
def test_hohmann_transfer_time_and_light_time():
    m = HohmannMission()
    assert 255 < m.tof_days < 262                   # textbook ~259 days
    g = MissionContext(start_day=200).status(0)
    assert 3 < g["one_way_light_time_min"] < 25


def test_blackout_queues_everything_and_priority_order():
    q = CommQueue()
    for i in range(3):
        q.enqueue(4, i, "telemetry", f"routine {i}")
    q.enqueue(1, 5, "medical_event", "critical")
    for t in range(10):
        q.step(t, "blackout", 10.0)
    assert q.pending() == 4                         # nothing sent, nothing dropped
    q.step(11, "delay", 10.0)                       # link back: bandwidth = 2 messages / min
    sent = {m.summary for m in q.messages if m.status == "in_transit"}
    assert "critical" in sent and len(sent) == 2    # P1 jumps the queue of older routine traffic


# ----------------------------------------------------------------- behavioral
def test_pvt_scoring_thresholds():
    rts = [250.0] * 40 + [400.0] * 5 + [100.0] * 2  # 5 lapses (>=355), 2 false starts (<130)
    r = score_pvt(rts, anticipations=1)
    assert r["valid"] and r["lapses"] == 5 and r["false_starts"] == 3
    assert not score_pvt([250.0] * 5)["valid"]


def test_behavioral_flags_sleep_restriction_not_control():
    from ares.behavioral.simulate import simulate_checkin, simulate_pvt

    def run(restrict):
        rng = np.random.default_rng(1)
        bp, debt, lvl = BehavioralProfile("X"), 0.0, 0
        for d in range(12):
            sl = 5.0 if (restrict and d >= 4) else 8.0
            debt = max(0.0, debt * 0.85 + max(0.0, 8.0 - sl))
            lvl = bp.add(BehavioralRecord(d, simulate_pvt(rng, 240, debt, 0), simulate_checkin(rng, sl, 8, debt, 0), sl))["level"]
        return lvl
    assert run(True) >= 1 and run(False) == 0


# ----------------------------------------------------------------- cabin
def test_cabin_attributes_crew_wide_change_to_co2():
    mon = CabinMonitor()
    for t in range(120):
        mon.update({"t": t, "ppco2_mmhg": 6.0, "temp_c": 22.5, "rh_pct": 45, "ppo2_mmhg": 158})
    crew = {f"A{i}": {"z": {"rr": 3.0}, "quality": {"rr": 1.0}} for i in range(4)}
    a = mon.assess(crew)
    assert a["level"] == 2 and a["attribution"]["cause"].startswith("environmental")


# ----------------------------------------------------------------- storage integrity
def test_hash_chain_detects_tampering(tmp_path):
    from ares.storage import LocalStore

    s = LocalStore(tmp_path / "t.db")
    for i in range(5):
        s.append("vitals", i, "A", {"hr": 60 + i})
    s.commit()
    assert s.verify()["vitals"]["intact"]
    s.db.execute("UPDATE vitals SET payload = '{\"hr\":200}' WHERE id = 3")
    s.db.commit()
    v = s.verify()["vitals"]
    assert not v["intact"] and v["first_bad_row"] == 3


# ----------------------------------------------------------------- engine + assistant + API
@pytest.fixture(scope="module")
def engine():
    from ares.engine import AresEngine

    e = AresEngine(baseline_days=1.0, with_ecg=False)
    for _ in range(5):
        e.tick()
    return e


def test_assistant_never_generates_and_declines_unknown(engine):
    from ares.assistant.assistant import Assistant

    a = Assistant(engine)
    r = a.ask("how do I perform an appendectomy")
    assert r["generated_text"] is False
    assert any("will not improvise" in str(s["items"]) for s in r["sections"])
    r2 = a.ask("what oxygen supplies do we have?")
    assert any(s["type"] == "inventory" for s in r2["sections"])


def test_blackout_scenario_detected_onboard(engine):
    engine.trigger("blackout_emergency", engine.crew[1].id)
    for _ in range(20):
        engine.tick()
    assert engine.mission.status(engine.t)["comm_mode"] == "blackout"
    assert engine.last[engine.crew[1].id]["cls"]["level"] >= 2
    rep = engine.incidents[engine.active[engine.crew[1].id]]["report"]
    assert "blackout" in rep["mission_context"]["comm_mode"]
    engine.clear_scenarios()


def test_api_endpoints():
    from fastapi.testclient import TestClient

    import ares.api.server as srv
    from ares.engine import AresEngine

    class FastRuntime(srv.Runtime):
        def __init__(self):
            import threading
            self.lock = threading.RLock()
            self.engine = AresEngine(baseline_days=1.0, with_ecg=False)
            self.assistant = srv.Assistant(self.engine)
            self.speed, self.paused, self.tick_ms, self.errors, self.last_error = 0.0, True, 0.0, 0, None
            self._stop = threading.Event()
            self.thread = threading.Thread(target=lambda: None, daemon=True)
            self.sim = srv.MissionSimulation(self)
            from ares.persistence import HistoryStore
            self.history = HistoryStore()
            from ares.assessments.store import TestStore
            self.tests, self.tests_error = TestStore(self.history), None
            self.tests.upsert_profiles(self.engine.crew)
            self.recovery, self.shutdown_done, self.gen, self._last_save = {}, False, 0, 0.0

    srv.RT = FastRuntime()
    with TestClient(srv.app) as c:
        assert c.get("/api/state").status_code == 200
        assert c.post("/api/scenario", json={"key": "spo2_drop", "astronaut_id": "AST-1"}).json()["ok"]
        assert c.post("/api/scenario", json={"key": "nope"}).status_code == 400
        assert c.post("/api/assistant", json={"question": "radiation dose?"}).status_code == 200
        r = c.post("/api/behavioral/AST-1/pvt", json={"rts_ms": [260.0] * 30, "anticipations": 0}).json()
        assert r["ok"] and r["result"]["lapses"] == 0
        assert c.post("/api/clinical/AST-1/symptoms", json={"symptoms": ["headache"]}).json()["ok"]
        assert c.get("/api/system").status_code == 200


def test_cmo_patient_during_cabin_event_regression():
    """Regression: CMO-as-patient rule + cabin attribution in the same report once crashed the clock."""
    from ares.engine import AresEngine

    e = AresEngine(baseline_days=1.0, with_ecg=False, load_models=False)
    cmo = next(p for p in e.crew if "CMO" in p.role)
    e.trigger("co2_buildup")
    e.trigger("cardiac_arrhythmia", cmo.id)
    for _ in range(150):
        e.tick()
    rep = e.incidents[e.active[cmo.id]]["report"]
    assert any("CREW MEDICAL OFFICER" in r for r in rep["reasons"])
