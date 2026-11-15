"""v0.3: mission simulation controller, emergency workflow, four-part guidance, drift, sync queue, API groups."""
import time

import pytest

from ares.behavioral.pvt import pvt_stats
from ares.mission.comms import CommQueue


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    import ares.api.server as srv
    srv.RT = None            # a real runtime with a running mission clock (other tests may leave a stub behind)
    with TestClient(srv.app) as c:
        yield c
    srv.RT._stop.set()


def test_simulation_start_pause_resume_stop_drive_real_engine(client):
    r = client.post("/api/simulation/start", json={"scenario": "respiratory", "astronaut_id": "AST-2", "speed": 30}).json()
    assert r["state"] == "running" and r["target"] == "AST-2"
    time.sleep(3)
    s = client.get("/api/simulation").json()
    assert s["elapsed_min"] > 10 and s["steps"][0]["done"]
    assert any(a["key"] == "respiratory" for a in client.get("/api/state").json()["active_scenarios"])
    assert client.post("/api/simulation/pause").json()["state"] == "paused"
    t1 = client.get("/api/mission").json()["t"]
    time.sleep(1.2)
    assert client.get("/api/mission").json()["t"] == t1          # paused -> no simulated time, no data generation
    assert client.post("/api/simulation/resume").json()["state"] == "running"
    assert client.post("/api/simulation/stop").json()["state"] == "stopped"
    assert client.get("/api/state").json()["active_scenarios"] == []
    assert client.post("/api/simulation/start", json={"scenario": "nope"}).status_code == 400


def test_emergency_workflow_actions_are_real(client):
    client.post("/api/simulation/start", json={"scenario": "blackout_emergency", "astronaut_id": "AST-3", "speed": 30})
    inc = None
    for _ in range(40):
        time.sleep(0.5)
        incs = [i for i in client.get("/api/emergencies").json()["incidents"] if i["astronaut_id"] == "AST-3" and i["status"] == "active"]
        if incs:
            inc = incs[0]["id"]
            break
    assert inc is not None, "no incident opened"
    client.post("/api/simulation/pause")
    for a in ("request_measurements", "verify_confirmed", "notify_crew", "acknowledge", "start_followup", "queue_earth"):
        assert client.post(f"/api/emergencies/{inc}/action", json={"action": a}).status_code == 200
    d = client.get(f"/api/emergencies/{inc}").json()
    steps = {s["key"]: s["state"] for s in d["workflow"]["steps"]}
    assert steps["verify"] == steps["notify"] == steps["acknowledge"] == steps["earth"] == "done"
    assert steps["monitor"] == "active"
    assert client.post(f"/api/emergencies/{inc}/action", json={"action": "close"}).status_code == 409   # still abnormal
    assert client.post(f"/api/emergencies/{inc}/action", json={"action": "bogus"}).status_code == 409
    assert "Event timeline" in client.get(f"/api/emergencies/{inc}/report.md").text
    # blackout: reports wait onboard with a reason
    msgs = d["workflow"]["earth_messages"]
    assert any(m["status"] == "queued" for m in msgs) and client.get("/api/mission").json()["mission"]["comm_mode"] == "blackout"
    g = d["guidance"]
    assert g["concern"] == "respiratory"
    assert set(g) >= {"what_is_happening", "immediate_action", "long_term_effects", "long_term_care"}
    assert all(p["approval"] for p in g["immediate_action"]["protocols"])        # only stored protocols
    assert all(e["evidence"] in ("established-spaceflight", "spaceflight-research", "theoretical") for e in g["long_term_effects"])
    client.post("/api/simulation/stop")


def test_escalation_is_a_floor_and_sends_p1(client):
    incs = client.get("/api/emergencies").json()["incidents"]
    inc = next((i for i in incs if i["status"] == "active" and i["level"] < 3), None)
    if inc is None:
        pytest.skip("no escalatable incident in this run")
    v = client.post(f"/api/emergencies/{inc['id']}/action", json={"action": "escalate", "note": "test"}).json()["workflow"]
    assert v["level"] == inc["level"] + 1 and v["escalated"]


def test_guidance_never_invents_for_unmonitored_regions(client):
    g = client.get("/api/medical-guidance?astronaut=AST-1&region=soleus_left").json()
    assert g["concern"] == "musculoskeletal" and g["immediate_action"]["protocols"] == []
    assert client.get("/api/medical-guidance?concern=unknown_x").status_code == 400


def test_drift_detects_gradual_cardiovascular_change():
    from ares.engine import AresEngine
    from ares.twin.drift import health_trends
    e = AresEngine(persist=False)
    a = e.crew[0].id
    for _ in range(240):
        e.tick()
    nominal = {r["key"]: r["status"] for r in health_trends(e.twins[a], e.baseline_end, e.t)["rows"]}
    e.trigger("gradual_cardiovascular", a)
    for _ in range(720):
        e.tick()
    rows = {r["key"]: r for r in health_trends(e.twins[a], e.baseline_end, e.t)["rows"]}
    assert nominal.get("hr") in ("stable", "insufficient", "watch")
    assert rows["hr"]["direction"] == "up" and rows["hr"]["status"] in ("watch", "gradual")


def test_comm_queue_dedupes_and_explains_waiting():
    q = CommQueue()
    a = q.enqueue(3, 0, "medical_event", "#1 X: L1")
    b = q.enqueue(2, 1, "medical_event", "#1 X: L1")
    assert a is b and a.priority == 2 and len(q.messages) == 1
    q.step(2, "blackout", 10)
    assert q.messages[0].status == "queued" and "Earth link down" in q.messages[0].waiting_note
    q.step(3, "connected", 10)
    assert q.messages[0].status == "in_transit"


def test_pvt_stats_definitions():
    s = pvt_stats([250, 260, 400, 100], anticipations=2, misses=1)
    assert s["premature"] == 3 and s["misses"] == 1 and s["lapses"] == 2      # 400 ms + the miss
    assert s["fastest_ms"] == 250 and s["slowest_ms"] == 400 and s["trials"] == 5


def test_api_groups_exist(client):
    for path in ("/api/astronauts", "/api/health?astronaut=AST-1", "/api/health/history?astronaut=AST-1", "/api/drift",
                 "/api/anomalies", "/api/emergencies", "/api/pvt/AST-1", "/api/mission", "/api/simulation",
                 "/api/medical-guidance?astronaut=AST-1", "/api/system/status", "/"):
        assert client.get(path).status_code == 200, path
    assert client.get("/api/health?astronaut=NOBODY").status_code == 404
    st = client.get("/api/system/status").json()
    assert st["internet_required"] is False and st["local_inference"]["anomaly_model"]
