"""Permanent test results (v0.5): storage, statuses, migration, integrity, exports, organ dossiers."""
import json
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

import ares.api.server as srv
from ares.assessments.store import TestStore
from ares.engine import AresEngine
from ares.persistence import HistoryStore


class Fast(srv.Runtime):
    def __init__(self, path):
        self.lock = threading.RLock()
        self.engine = AresEngine(baseline_days=1.0, with_ecg=False)
        self.assistant = srv.Assistant(self.engine)
        self.speed, self.paused, self.tick_ms, self.errors, self.last_error = 0.0, True, 0.0, 0, None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=lambda: None, daemon=True)
        self.sim = srv.MissionSimulation(self)
        self.history = HistoryStore(path=path)
        self.tests, self.tests_error = TestStore(self.history), None
        self.tests.upsert_profiles(self.engine.crew)
        self.recovery, self.shutdown_done, self.gen, self._last_save = {}, False, 0, 0.0


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("tests") / "history.db"
    srv.RT = Fast(db)
    with TestClient(srv.app) as c:
        c.db_path = db
        yield c


def trials(n, rt=260.0, extra=()):
    out = [{"trial_no": i + 1, "outcome": "lapse" if rt >= 355 else "response", "rt_ms": rt + (i % 5) * 7,
            "isi_ms": 3000, "t_offset_ms": i * 3500} for i in range(n)]
    for k, oc in enumerate(extra, start=n + 1):
        out.append({"trial_no": k, "outcome": oc, "rt_ms": None})
    return out


def run(c, aid, n, status, extra=()):
    tid = c.post("/api/tests/sessions", json={"astronaut_id": aid}).json()["test_id"]
    tr = trials(n, extra=extra)
    for i in range(0, len(tr), 7):
        assert c.post(f"/api/tests/sessions/{tid}/trials", json={"trials": tr[i:i + 7]}).status_code == 200
    r = c.post(f"/api/tests/sessions/{tid}/finish", json={"status": status, "duration_s": 120}).json()
    return tid, r


def test_completed_test_is_saved_with_trials_and_metrics(client):
    tid, r = run(client, "AST-1", 24, "completed", extra=("miss", "premature"))
    assert r["persisted"]["verified"] and r["persisted"]["status"] == "completed" and r["persisted"]["trials_saved"] == 26
    t = client.get(f"/api/tests/{tid}").json()
    m = t["result"]["metrics"]
    assert t["result"]["scored"] is True
    assert m["misses"] == 1 and m["premature_no_stimulus"] == 1 and m["responses"] == 24
    assert m["lapses"] == 1                                 # the miss counts as a lapse; no RT >= 355 ms
    rts = [x["rt_ms"] for x in t["trials"] if x["rt_ms"] is not None]
    assert m["mean_rt_ms"] == round(sum(rts) / len(rts), 1) and m["fastest_ms"] == min(rts)


def test_resent_trials_are_not_duplicated(client):
    tid = client.post("/api/tests/sessions", json={"astronaut_id": "AST-2"}).json()["test_id"]
    tr = trials(5)
    client.post(f"/api/tests/sessions/{tid}/trials", json={"trials": tr})
    r = client.post(f"/api/tests/sessions/{tid}/trials", json={"trials": tr}).json()
    assert r["trials_saved"] == 5
    a = client.post(f"/api/tests/sessions/{tid}/finish", json={"status": "stopped"}).json()
    b = client.post(f"/api/tests/sessions/{tid}/finish", json={"status": "completed"}).json()
    assert b["already_saved"] and b["test"]["status"] == "stopped"          # a retry never relabels or duplicates
    assert a["persisted"]["test_id"] == b["persisted"]["test_id"]
    assert client.post(f"/api/tests/sessions/{tid}/trials", json={"trials": trials(1)}).status_code == 409


def test_stopped_and_terminated_are_not_marked_completed_or_scored(client):
    for status in ("stopped", "terminated"):
        tid, r = run(client, "AST-1", 25, status)
        t = r["test"]
        assert t["status"] == status and t["result"]["scored"] is False
        assert any(status in x["text"] for x in t["result"]["interpretation"])


def test_missing_values_stay_missing(client):
    tid, r = run(client, "AST-3", 0, "stopped", extra=("miss", "miss", "premature"))
    m = r["test"]["result"]["metrics"]
    for k in ("mean_rt_ms", "median_rt_ms", "fastest_ms", "slowest_ms", "sd_ms", "cv", "response_speed"):
        assert m[k] is None
    assert m["misses"] == 2 and m["lapses"] == 2


def test_invalid_trials_rejected(client):
    tid = client.post("/api/tests/sessions", json={"astronaut_id": "AST-1"}).json()["test_id"]
    assert client.post(f"/api/tests/sessions/{tid}/trials", json={"trials": [{"trial_no": 1, "outcome": "boom"}]}).status_code == 400
    assert client.post(f"/api/tests/sessions/{tid}/trials",
                       json={"trials": [{"trial_no": 1, "outcome": "miss", "rt_ms": 300}]}).status_code == 400
    assert client.post(f"/api/tests/sessions/{tid}/finish", json={"status": "great"}).status_code == 400
    assert client.post("/api/tests/sessions", json={"astronaut_id": "NOPE"}).status_code == 404


def test_baseline_comparison_and_trends(client):
    for _ in range(3):
        run(client, "AST-4", 22, "completed")
    tid, r = run(client, "AST-4", 22, "completed")
    res = r["test"]["result"]
    assert res["baseline"]["established"] and res["comparison"]["baseline"]["mean_rt_ms"] is not None
    assert res["comparison"]["previous"] is not None
    tr = client.get("/api/tests/trends?astronaut=AST-4").json()
    assert tr["n_tests"] == 4 and tr["observed"] and all(o["category"].startswith("Observed") for o in tr["observed"])
    assert tr["model"]["category"] == "Model-generated assessment"
    assert "not a diagnosis" in tr["note"]


def test_one_step_assessments_saved(client):
    r = client.post("/api/behavioral/AST-1/checkin", json={"samn_perelli": 5, "mood": 5, "stress": 6, "workload": 7,
                                                           "sleep_quality": 4}).json()
    assert r["persisted"]["verified"]
    assert client.post("/api/clinical/AST-1/symptoms", json={"symptoms": ["headache"]}).json()["persisted"]["verified"]
    r = client.post("/api/clinical/AST-1/labs", json={"creatinine": 1.8, "alt": 30}).json()
    assert r["persisted"]["verified"] and r["assessment"]["flag_keys"] == ["creatinine"]   # kidney markers accepted
    assert client.post("/api/clinical/AST-1/labs", json={}).status_code == 400              # nothing invented/recorded
    types = {t["test_type"] for t in client.get("/api/tests?astronaut=AST-1").json()["tests"]}
    assert {"pvt", "wellness_checkin", "symptom_report", "lab_panel"} <= types


def test_legacy_one_shot_endpoint_saves_full_record(client):
    r = client.post("/api/pvt/AST-2", json={"rts_ms": [250 + i for i in range(22)], "anticipations": 1, "misses": 1}).json()
    t = client.get(f"/api/tests/{r['persisted']['test_id']}").json()
    assert t["status"] == "completed" and len(t["trials"]) == 24 and r["ok"]


def test_filters_and_exports(client):
    allr = client.get("/api/tests").json()["tests"]
    assert len(allr) == len({t["test_id"] for t in allr})
    st = client.get("/api/tests?status=stopped").json()["tests"]
    assert st and all(t["status"] == "stopped" for t in st)
    assert all(t["astronaut_id"] == "AST-4" for t in client.get("/api/tests?astronaut=AST-4").json()["tests"])
    future = client.get(f"/api/tests?date_from={time.time() + 3600}").json()["tests"]
    assert future == []
    tid = next(t["test_id"] for t in allr if t["test_type"] == "pvt" and t["status"] == "completed")
    csv = client.get(f"/api/tests/{tid}/export.csv")
    assert csv.status_code == 200 and "trial,outcome,reaction_time_ms" in csv.text
    pdf = client.get(f"/api/tests/{tid}/export.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert client.get("/api/tests/export.csv").text.startswith("test_id,date")


def test_interrupted_after_restart_and_history_kept(tmp_path):
    db = tmp_path / "h.db"
    h1 = HistoryStore(path=db)
    s1 = TestStore(h1)
    from ares.engine import AresEngine
    s1.upsert_profiles(AresEngine(baseline_days=1.0, with_ecg=False).crew[:1])
    tid = s1.create("AST-1", "pvt", {}, 1.0, 10.0, "test")
    s1.add_trials(tid, trials(3))
    done = s1.create("AST-1", "pvt", {}, 1.0, 11.0, "test")
    s1.add_trials(done, trials(21))
    s1.finish(done, "completed", 100, {"metrics": {"mean_rt_ms": 260}, "scored": True})
    h1.db.close()                                               # crash: nothing else runs
    h2 = HistoryStore(path=db)
    s2 = TestStore(h2)
    t = s2.get(tid)
    assert s2.recovered_interrupted == 1 and t["status"] == "interrupted" and len(t["trials"]) == 3
    assert t["result"]["metrics"]["responses"] == 3 and t["result"]["scored"] is False
    assert s2.get(done)["status"] == "completed" and len(s2.get(done)["trials"]) == 21


def test_migration_keeps_v04_reaction_tests(tmp_path):
    db = tmp_path / "old.db"
    h = HistoryStore(path=db)                                    # v0.4 layout: pvt_runs table only
    run_ = {"id": 1, "t": 2900, "mission_day": 200.1, "duration_s": 180, "trials": 25, "valid": True,
            "stats": {"mean_rt_ms": 271.0, "lapses": 1, "rts_ms": [250.0, 260.0, 400.0]}, "score": {"valid": True}}
    h.db.execute("INSERT INTO pvt_runs (session, aid, saved, payload) VALUES (1, 'AST-1', ?, ?)",
                 (time.time(), json.dumps(run_)))
    h.db.commit()
    assert h.db.execute("PRAGMA user_version").fetchone()[0] == 0
    s = TestStore(h)
    assert s.migrations and h.db.execute("PRAGMA user_version").fetchone()[0] == 2
    t = s.get("LEGACY-00001")
    assert t["status"] == "legacy" and [x["outcome"] for x in t["trials"]] == ["response", "response", "lapse"]
    assert h.db.execute("SELECT COUNT(*) FROM pvt_runs").fetchone()[0] == 1          # original rows untouched
    TestStore(h)                                                                   # idempotent
    assert h.db.execute("SELECT COUNT(*) FROM test_sessions").fetchone()[0] == 1


def test_database_errors_are_reported_not_hidden(tmp_path):
    h = HistoryStore(path=tmp_path / "x.db")
    s = TestStore(h)
    from ares.assessments.store import StoreError
    h.db.close()
    with pytest.raises((StoreError, sqlite3.ProgrammingError)):
        s.create("AST-1", "pvt", {}, 1, 1, "test")


# ------------------------------------------------------------------ organ dossiers
def test_organ_events_are_specific_and_not_mixed(client):
    e = srv.RT.engine
    e.trigger("spo2_drop", "AST-1")
    for _ in range(70):
        e.tick()
    lungs = client.get("/api/organs/lung_left?astronaut=AST-1").json()
    assert lungs["group"] == "lungs" and lungs["active_alert"]
    for ev in lungs["events"]:
        assert set(ev["measurements"]) <= {"spo2", "rr"}
        assert ev["anatomical_region"] == "lungs" and ev["astronaut_id"] == "AST-1"
        for m in ev["measurements"].values():
            live = e.last["AST-1"]["state"]["values"][m["key"]]
            assert m["current"] == round(float(live), 1)                         # the actual backend value
    assert any(p["id"] == "RESP-01" for ev in lungs["events"] for p in ev["recommended_actions"])
    heart = client.get("/api/organs/heart?astronaut=AST-1").json()
    for ev in heart["events"]:
        assert set(ev["measurements"]) <= {"hr", "hrv_rmssd", "sbp", "dbp"}
    other = client.get("/api/organs/lung_right?astronaut=AST-3").json()      # another astronaut: nothing mixed in
    assert not other["active_alert"]
    assert client.get("/api/organs/lung_left?astronaut=AST-1").json()["events"][0]["event_id"].startswith("AST-1-LUNGS")


def test_unmonitored_organs_say_so(client):
    for region in ("stomach", "spleen", "bladder", "kidney_left"):
        d = client.get(f"/api/organs/{region}?astronaut=AST-3").json()
        assert d["data_available"] is False
        assert d["message"] == "No sufficient monitoring data available for this organ."
        assert d["measurements"] == {} and not d["events"]
    mus = client.get("/api/organs/soleus_left?astronaut=AST-3").json()
    assert mus["data_available"] is False and all(m["category"] != "direct sensor measurement" for m in mus["measurements"].values())
    bone = client.get("/api/organs/tibia_left?astronaut=AST-3").json()
    pe = bone["population_estimate"]
    assert pe["category"] == "population estimate" and "NOT a measurement" in pe["caveat"]
    assert pe["per_region"]["skull"]["applies"] is False


def test_brain_panel_shows_saved_reaction_tests(client):
    run(client, "AST-2", 22, "completed")
    b = client.get("/api/organs/brain?astronaut=AST-2").json()
    assert b["group"] == "brain" and b["history"]["saved_tests"]
    assert b["measurements"]["mean_rt_ms"]["category"] == "test result"
    assert b["model_assessment"]["category"] == "Model-generated assessment"
    assert "structural" not in b["what_is_happening"].lower() or "not" in b["what_is_happening"].lower()


def test_organ_summary_lists_every_group(client):
    s = client.get("/api/organs?astronaut=AST-1").json()
    groups = {o["group"] for o in s["organs"]}
    assert {"heart", "lungs", "brain", "kidneys", "liver", "muscles", "skeleton"} <= groups
