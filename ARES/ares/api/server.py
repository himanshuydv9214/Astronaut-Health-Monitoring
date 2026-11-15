"""ARES API + dashboard server (local, offline-first).

    python -m ares.api.server            # http://127.0.0.1:8000
    ARES_SPEED=4 python -m ares.api.server

A background thread advances the mission clock (default 2 mission-minutes per
real second). All endpoints read/write the single in-process engine under a
lock. Nothing here needs the internet: the UI, Plotly and fonts are served
locally.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
import threading
import time
import traceback
from pathlib import Path

import plotly
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ares.api import tests_api
from ares.assessments.store import StoreError
from ares.assistant.assistant import Assistant
from ares.engine import AresEngine
from ares.emergency import guidance, workflow
from ares.simulation.mission_sim import MissionSimulation
from ares.simulation.scenarios import UI_SCENARIO_KEYS

WEB = Path(__file__).resolve().parents[1] / "web"
PLOTLY_JS = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"


class Runtime:
    def __init__(self):
        from ares import startup_status as ss
        from ares.paths import APP_ROOT, ensure_dirs
        from ares.persistence import HistoryStore, startup_recovery
        ensure_dirs()
        self.lock = threading.RLock()
        ss.mark("recovery", "running", "checking databases and making a backup")
        self.recovery = startup_recovery()
        ss.mark("recovery", "error" if self.recovery["errors"] else "ok",
                "; ".join(self.recovery["errors"]) or f"backup {self.recovery['backup'] or 'not needed (first start)'}"
                + (f"; restored {len(self.recovery['restored'])} database(s) from backup" if self.recovery["restored"] else ""))
        ss.mark("database", "running", "opening local databases")
        from ares import __version__
        self.history = HistoryStore(app_version=__version__)
        self.tests_error = None
        try:                                   # permanent test results live in the same database (schema migrated)
            from ares.assessments.store import TestStore
            self.tests = TestStore(self.history)
        except Exception as ex:  # noqa: BLE001 - the app still runs; saving tests reports the problem
            self.tests, self.tests_error = None, str(ex)
        ss.mark("models", "running", "loading AI models and building the crew's personal baselines (~15 s)")
        self.engine = AresEngine(persist=True)
        self._restore_history()
        if self.tests is not None:
            self.tests.upsert_profiles(self.engine.crew)
        ss.mark("database", "ok" if self.engine.store is not None else "error",
                f"SQLite at {self.engine.store.path}" if self.engine.store is not None else "local store unavailable")
        ok = self.engine.anomaly.ready and self.engine.forecaster.ready
        ss.mark("models", "ok" if ok else "error", "unusual-pattern model + 30-min risk model loaded locally" if ok else
                "trained model files missing or unreadable in models/ - run scripts/train_models.py")
        ss.mark("knowledge", "ok", f"{len(self.engine.kb.protocols)} procedures, v{self.engine.kb.meta['version']}")
        glb = APP_ROOT / "assets" / "anatomy" / "ares_body.glb"
        ss.mark("anatomy", "ok" if glb.exists() else "error",
                f"{glb.stat().st_size / 1e6:.1f} MB BodyParts3D model" if glb.exists() else f"missing {glb}")
        self.assistant = Assistant(self.engine)
        self.speed = float(os.environ.get("ARES_SPEED", 2.0))   # mission minutes per real second
        self.paused = False
        self.tick_ms = 0.0
        self.errors = 0
        self.last_error = None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.sim = MissionSimulation(self)
        self._last_save = time.time()
        self.shutdown_done = False
        self.gen = 0          # increases on every simulation reset (fresh engine)

    def _restore_history(self):
        """Earlier sessions' reaction-time tests are shown again (history only - nothing is re-executed)."""
        for aid, runs in self.history.previous_pvt_runs().items():
            if aid in self.engine.by_id:
                self.engine.pvt_runs[aid] = runs[-50:] + self.engine.pvt_runs.get(aid, [])

    def save_state(self):
        with self.lock:
            self.history.save_incidents(self.engine, workflow.status_of, self.gen)
            st = self.sim.status()
            self.history.save_sim(st, self.sim.t_start)
            if self.engine.store is not None:
                self.engine.store.commit()
        self._last_save = time.time()

    def shutdown(self):
        """Graceful stop: clock, final save, clean-session flag, close databases. Idempotent."""
        if self.shutdown_done:
            return
        self._stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=5)
        try:
            self.save_state()
            self.history.end_session()
        finally:
            self.history.close()
            if self.engine.store is not None:
                self.engine.store.close()
            self.shutdown_done = True

    def _loop(self):
        acc = 0.0
        last = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            dt, last = now - last, now
            if not self.paused:
                acc += dt * self.speed
                n = 0
                while acc >= 1.0 and n < 30:
                    t0 = time.perf_counter()
                    try:
                        with self.lock:
                            self.engine.tick()
                            self.sim.update()
                    except Exception as ex:   # fault tolerance: never let one bad minute stop monitoring
                        self.errors += 1
                        self.last_error = f"{type(ex).__name__}: {ex}"[:300]
                        traceback.print_exc()
                        with self.lock:
                            self.engine.t += 1.0      # skip the faulty minute, keep the mission clock running
                            self.engine._log(f"SOFTWARE FAULT contained ({self.last_error[:80]}) - monitoring continues", 2)
                    self.tick_ms = 0.9 * self.tick_ms + 0.1 * (time.perf_counter() - t0) * 1000
                    acc -= 1.0
                    n += 1
                if n == 30:
                    acc = 0.0   # cannot keep up: drop backlog rather than spiral
            if time.time() - self._last_save > 30:
                try:
                    self.save_state()
                except Exception:  # noqa: BLE001 - persistence problems must never stop monitoring
                    traceback.print_exc()
                    self._last_save = time.time()
            time.sleep(0.05)


RT: Runtime | None = None


@asynccontextmanager
async def lifespan(_app):
    from ares import startup_status as ss
    try:
        rt()          # build the engine (baseline acquisition) and start the mission clock
    except Exception as ex:
        ss.mark("server", "error", f"{type(ex).__name__}: {ex}")
        raise
    ss.mark("interface", "ok" if (WEB3D / "index.html").exists() else "error",
            "built interface found" if (WEB3D / "index.html").exists() else "ares/web3d_dist missing - run npm run build")
    ss.mark("server", "ok", "listening on 127.0.0.1")
    yield
    if RT is not None:
        RT.shutdown()


app = FastAPI(title="ARES - Autonomous Risk Evaluation & Emergency Support", version="0.5.0", lifespan=lifespan)
tests_api.bind(lambda: rt())
app.include_router(tests_api.router)
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
TOKEN = os.environ.get("ARES_TOKEN")   # optional local auth for write actions (off by default on the demo laptop)


@app.middleware("http")
async def local_auth(request: Request, call_next):
    if TOKEN and request.method == "POST" and request.headers.get("x-ares-token") != TOKEN:
        return JSONResponse({"ok": False, "error": "missing or wrong X-ARES-Token"}, status_code=401)
    return await call_next(request)
ANATOMY_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "anatomy"
WEB3D = Path(__file__).resolve().parents[1] / "web3d_dist"
app.mount("/anatomy-assets", StaticFiles(directory=str(ANATOMY_ASSETS)), name="anatomy")
if WEB3D.exists():
    app.mount("/app", StaticFiles(directory=str(WEB3D)), name="app")


def rt() -> Runtime:
    global RT
    if RT is None:
        RT = Runtime()
        RT.thread.start()
    return RT


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    """Main ARES command interface (React, prebuilt). Falls back to the classic dashboard if not built."""
    return FileResponse(WEB3D / "index.html" if (WEB3D / "index.html").exists() else WEB / "index.html")


@app.get("/classic")
@app.get("/classic/")
def classic():
    return FileResponse(WEB / "index.html")


@app.get("/twin")
@app.get("/twin/")
def twin_redirect():
    return RedirectResponse("/#/body")


@app.get("/vendor/plotly.min.js")
def plotly_js():
    return FileResponse(PLOTLY_JS, media_type="application/javascript")


# ------------------------------------------------------------------ state
@app.get("/api/state")
def state(astronaut: str | None = None):
    r = rt()
    with r.lock:
        s = r.engine.snapshot(astronaut)
        sim = r.sim.status()
    s["runtime"] = {"speed": r.speed, "paused": r.paused, "tick_ms": round(r.tick_ms, 2), "errors": r.errors}
    s["simulation"] = {k: sim[k] for k in ("state", "scenario", "title", "elapsed_min", "progress", "target_name")}
    return JSONResponse(s)


class ScenarioReq(BaseModel):
    key: str
    astronaut_id: str | None = None


@app.post("/api/scenario")
def scenario(req: ScenarioReq):
    if req.key not in UI_SCENARIO_KEYS:
        raise HTTPException(400, f"unknown scenario {req.key}")
    with rt().lock:
        return rt().engine.trigger(req.key, req.astronaut_id)


@app.post("/api/clear")
def clear():
    with rt().lock:
        rt().engine.clear_scenarios()
    return {"ok": True}


class ModeReq(BaseModel):
    mode: str | None = None   # connected | delay | blackout | None (auto)


@app.post("/api/comm")
def comm(req: ModeReq):
    with rt().lock:
        rt().engine.set_comm_override(req.mode)
    return {"ok": True}


class FlagReq(BaseModel):
    on: bool


@app.post("/api/shelter")
def shelter(req: FlagReq):
    with rt().lock:
        rt().engine.set_shelter(req.on)
    return {"ok": True}


class AckReq(BaseModel):
    incident_id: int


@app.post("/api/ack")
def ack(req: AckReq):
    with rt().lock:
        return {"ok": rt().engine.acknowledge(req.incident_id)}


class SpeedReq(BaseModel):
    minutes_per_second: float = Field(ge=0.0, le=60.0)
    paused: bool | None = None


@app.post("/api/speed")
def speed(req: SpeedReq):
    r = rt()
    r.speed = req.minutes_per_second
    if req.paused is not None:
        r.paused = req.paused
    return {"speed": r.speed, "paused": r.paused}


class DayReq(BaseModel):
    day: float = Field(ge=0, le=900)


@app.post("/api/mission_day")
def mission_day(req: DayReq):
    with rt().lock:
        rt().engine.set_mission_day(req.day)
    return {"ok": True}


@app.get("/api/report/{inc_id}")
def report(inc_id: int):
    with rt().lock:
        inc = rt().engine.incidents.get(inc_id)
        if not inc:
            raise HTTPException(404, "no such incident")
        return {"incident": rt().engine.incident_summary(inc), "report": inc["report"]}


# ------------------------------------------------------------------ assistant
class AskReq(BaseModel):
    question: str = Field(max_length=500)
    astronaut_id: str | None = None


@app.post("/api/assistant")
def ask(req: AskReq):
    with rt().lock:
        return rt().assistant.ask(req.question, req.astronaut_id)


# ------------------------------------------------------------------ behavioral (private channel)
class PVTReq(BaseModel):
    rts_ms: list[float] = Field(max_length=400)
    status: str = Field(default="completed", pattern="^(completed|stopped|terminated)$")
    anticipations: int = Field(ge=0, le=200, default=0)
    misses: int = Field(ge=0, le=200, default=0)
    duration_s: float | None = Field(default=None, ge=0, le=900)
    trials: int | None = Field(default=None, ge=0, le=500)


class CheckinReq(BaseModel):
    samn_perelli: int = Field(ge=1, le=7)
    mood: float = Field(ge=0, le=10)
    stress: float = Field(ge=0, le=10)
    workload: float = Field(ge=0, le=10, default=5)
    sleep_quality: float = Field(ge=0, le=10)


@app.get("/api/behavioral/{aid}")
def behavioral(aid: str):
    with rt().lock:
        return rt().engine.behavioral_view(aid)


@app.post("/api/behavioral/{aid}/pvt")
def pvt(aid: str, req: PVTReq):
    """One-shot submission (classic dashboard / older clients). Saved permanently with its trials."""
    r = rt()
    with r.lock:
        if aid not in r.engine.by_id:
            raise HTTPException(404, "unknown astronaut")
        if r.tests is None:
            raise HTTPException(503, "test database unavailable - result not saved")
        try:
            persisted = tests_api.save_legacy_pvt(r, aid, req.rts_ms, req.anticipations, req.misses, req.duration_s,
                                                  req.status)
        except StoreError as ex:
            raise HTTPException(500, f"not saved: {ex}") from ex
        t = r.tests.get(persisted["test_id"])
        res = t["result"]
        run = r.engine.pvt_runs.get(aid, [None])[-1] if req.status == "completed" else None
        return {"ok": res["scored"], "result": res["score"], "assessment": res["assessment"], "run": run,
                "persisted": persisted, "test": t}


@app.post("/api/behavioral/{aid}/checkin")
def checkin(aid: str, req: CheckinReq):
    r = rt()
    with r.lock:
        if aid not in r.engine.by_id:
            raise HTTPException(404, "unknown astronaut")
        out = r.engine.submit_checkin(aid, req.model_dump())
        a = out["assessment"]
        out["persisted"] = tests_api.save_single(
            r, aid, "wellness_checkin", {"scales": {"samn_perelli": "1-7 (1 fully alert)", "others": "0-10"}},
            req.model_dump(), {"category": "Model-generated assessment", "level": a["level"], "label": a["label"]},
            [{"kind": "note", "s": "stable", "text": "Self-reported ratings; combined with reaction tests and sleep by the "
                                                     "behavioral readiness model."}])
        return out


# ------------------------------------------------------------------ clinical: symptoms & labs
class SymptomReq(BaseModel):
    symptoms: list[str] = Field(max_length=20)


class LabReq(BaseModel):
    wbc: float | None = Field(default=None, ge=0, le=100)
    lymphocytes: float | None = Field(default=None, ge=0, le=50)
    neutrophils: float | None = Field(default=None, ge=0, le=80)
    crp: float | None = Field(default=None, ge=0, le=500)
    creatinine: float | None = Field(default=None, ge=0, le=20)      # kidney markers (mg/dL)
    bun: float | None = Field(default=None, ge=0, le=200)
    alt: float | None = Field(default=None, ge=0, le=5000)           # liver enzymes (U/L)
    ast: float | None = Field(default=None, ge=0, le=5000)


@app.post("/api/clinical/{aid}/symptoms")
def symptoms(aid: str, req: SymptomReq):
    with rt().lock:
        if aid not in rt().engine.by_id:
            raise HTTPException(404, "unknown astronaut")
        out = rt().engine.submit_symptoms(aid, req.symptoms)
        out["persisted"] = tests_api.save_single(rt(), aid, "symptom_report", None,
                                                 {"symptoms": out["record"]["symptoms"]})
        return out


@app.post("/api/clinical/{aid}/labs")
def labs(aid: str, req: LabReq):
    vals = {k: v for k, v in req.model_dump().items() if v is not None}
    if not vals:
        raise HTTPException(400, "no lab values given - nothing recorded")
    with rt().lock:
        if aid not in rt().engine.by_id:
            raise HTTPException(404, "unknown astronaut")
        out = rt().engine.submit_labs(aid, vals)
        out["persisted"] = tests_api.save_single(rt(), aid, "lab_panel", None,
                                                 {"values": vals, "flags": out["assessment"].get("flags", [])})
        return out


# ------------------------------------------------------------------ 3D anatomical digital twin
@app.get("/api/anatomy")
def anatomy(astronaut: str | None = None):
    from ares.anatomy.mapping import region_states
    with rt().lock:
        aid = astronaut if astronaut in rt().engine.by_id else rt().engine.crew[0].id
        return region_states(rt().engine, aid)


@app.get("/api/anatomy/history")
def anatomy_history(astronaut: str | None = None, minutes: int = 720):
    from ares.anatomy.mapping import history_states
    with rt().lock:
        aid = astronaut if astronaut in rt().engine.by_id else rt().engine.crew[0].id
        return history_states(rt().engine, aid, max(10, min(minutes, 720)))


@app.get("/api/anatomy/regions")
def anatomy_regions():
    from ares.anatomy.mapping import load_regions
    return load_regions()


@app.get("/api/provenance")
def provenance():
    from ares.realdata.provenance import provenance_records
    return provenance_records()


@app.get("/api/organs")
def organs(astronaut: str):
    """All organ groups with their current state (multiple active abnormalities at a glance)."""
    from ares.anatomy.organs import organs_summary
    with rt().lock:
        return organs_summary(rt().engine, _aid(astronaut))


@app.get("/api/organs/{region}")
def organ(region: str, astronaut: str):
    """Organ dossier for a clicked 3D region: actual events, measurements vs baseline, evidence, onboard guidance,
    long-term considerations, history and previous alerts. Unmonitored organs say so explicitly."""
    from ares.anatomy.organs import organ_report
    r = rt()
    with r.lock:
        return organ_report(r.engine, r, _aid(astronaut), region)


@app.websocket("/ws/anatomy")
async def ws_anatomy(ws: WebSocket):
    """Pushes the anatomical state about once per second (falls back to polling in the client)."""
    import asyncio

    from ares.anatomy.mapping import region_states
    await ws.accept()
    aid = ws.query_params.get("astronaut")
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                aid = msg.get("astronaut", aid)
            except asyncio.TimeoutError:
                pass
            with rt().lock:
                a = aid if aid in rt().engine.by_id else rt().engine.crew[0].id
                payload = region_states(rt().engine, a)
            await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError):
        return


# ------------------------------------------------------------------ system health
@app.get("/api/system")
def system():
    r = rt()
    with r.lock:
        return r.engine.system_health() | {"tick_ms": round(r.tick_ms, 2), "speed": r.speed,
                                           "software_faults_contained": r.errors, "last_fault": r.last_error}


@app.post("/api/donki/refresh")
def donki_refresh():
    from ares.radiation.donki import fetch_sep

    try:
        ev = fetch_sep()
        return {"ok": True, "events": len(ev)}
    except ConnectionError as e:
        return {"ok": False, "offline": True, "detail": str(e)[:200],
                "note": "Expected on board: ARES keeps using the cached DONKI records."}


# ------------------------------------------------------------------ v0.3 API groups (used by the new interface)
def _aid(a: str | None) -> str:
    e = rt().engine
    if a is None:
        return e.crew[0].id
    if a not in e.by_id:
        raise HTTPException(404, f"unknown astronaut '{a}'")
    return a


def _inc(inc_id: int) -> dict:
    inc = rt().engine.incidents.get(inc_id)
    if inc is None:
        raise HTTPException(404, f"no incident #{inc_id}")
    return inc


@app.get("/api/astronauts")
def astronauts():
    with rt().lock:
        e = rt().engine
        rows = {c["id"]: c for c in e.crew_summary()}
        return [{"id": p.id, "name": p.name, "role": p.role, "age": p.age, "simulated": True} | rows.get(p.id, {})
                for p in e.crew]


@app.get("/api/health")
def health(astronaut: str | None = None):
    with rt().lock:
        e = rt().engine
        a = _aid(astronaut)
        return {"summary": next(c for c in e.crew_summary() if c["id"] == a), "detail": e.astronaut_detail(a)}


@app.get("/api/health/history")
def health_history(astronaut: str | None = None):
    from ares.twin.drift import health_trends
    with rt().lock:
        e = rt().engine
        a = _aid(astronaut)
        return health_trends(e.twins[a], e.baseline_end, e.t) | {"astronaut_id": a, "t0": e.baseline_end,
                                                                 "longitudinal_daily": e.twins[a].longitudinal()[-14:]}


@app.get("/api/drift")
def drift(astronaut: str | None = None):
    return health_history(astronaut)


@app.get("/api/anomalies")
def anomalies(astronaut: str | None = None):
    with rt().lock:
        e = rt().engine
        a = _aid(astronaut)
        d = e.astronaut_detail(a)
        L = e.last[a]
        return {"classification": d["classification"], "patterns": d["patterns"], "explanation": d["explanation"],
                "anomaly_score": L.get("anomaly"), "risk_30min": L.get("risk"), "news2": d["news2"],
                "recent": {k: d["recent"][k] for k in ("t", "anomaly", "risk", "level")}, "correlations": d["correlations"]}


@app.get("/api/emergencies")
def emergencies():
    with rt().lock:
        e = rt().engine
        incs = sorted(e.incidents.values(), key=lambda i: (workflow.status_of(i) == "closed", i["closed"] is not None,
                                                           -i["level"], -i["opened"]))
        return {"t": e.t, "t0": e.baseline_end, "comm_mode": e.mission.status(e.t)["comm_mode"],
                "incidents": [workflow.view(e, i) | {"steps": None, "timeline": None} for i in incs[:40]],
                "sync": e.comms.stats(e.t)}


@app.get("/api/emergencies/{inc_id}")
def emergency(inc_id: int):
    with rt().lock:
        e = rt().engine
        inc = _inc(inc_id)
        aid = inc["astronaut_id"] if inc["astronaut_id"] in e.by_id else None
        return {"workflow": workflow.view(e, inc), "report": inc.get("report"),
                "guidance": guidance.build(e, aid, incident=inc), "t": e.t, "t0": e.baseline_end,
                "history": e._columns(aid, 180) if aid else None}


class ActionReq(BaseModel):
    action: str
    note: str | None = Field(default=None, max_length=300)


@app.post("/api/emergencies/{inc_id}/action")
def emergency_action(inc_id: int, req: ActionReq):
    with rt().lock:
        e = rt().engine
        inc = _inc(inc_id)
        try:
            v = workflow.act(e, inc, req.action, req.note)
        except ValueError as ex:
            raise HTTPException(409, str(ex)) from ex
        if e.store is not None:
            e.store.commit()
        try:                       # crew decisions are written to the history immediately (crash / power-loss safety)
            rt().save_state()
        except Exception:  # noqa: BLE001 - never block a crew action on the archive
            pass
        return {"ok": True, "workflow": v}


@app.get("/api/emergencies/{inc_id}/report.md")
def emergency_report(inc_id: int):
    with rt().lock:
        e = rt().engine
        md = workflow.report_markdown(e, _inc(inc_id))
    return PlainTextResponse(md, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="ARES_incident_{inc_id}.md"'})


@app.get("/api/pvt/{aid}")
def pvt_history(aid: str):
    with rt().lock:
        e = rt().engine
        a = _aid(aid)
        bv = e.behavioral_view(a)
        cl = e.astronaut_detail(a)
        saved = r_tests_runs(a)
        return {"runs": saved if saved is not None else e.pvt_runs.get(a, [])[::-1], "series": bv["series"],
                "assessment": bv["assessment"], "saved_permanently": saved is not None,
                "sleep_h_24h": e.last[a]["state"]["sleep_h_24h"] if e.last[a] else None,
                "protocol": {"name": "PVT-B (3-minute Psychomotor Vigilance Test, brief)", "isi_s": [2, 5],
                             "lapse_ms": 355, "false_start_ms": 130, "miss_ms": 10000, "standard_duration_s": 180,
                             "source": "Basner, Mollicone & Dinges 2011; ISS Reaction Self Test"},
                "timeline": cl["timeline"][:10]}


def r_tests_runs(aid: str) -> list[dict] | None:
    """Saved reaction tests of all sessions (newest first) in the shape the Alertness page uses."""
    store = getattr(rt(), "tests", None)
    if store is None:
        return None
    out = []
    for x in store.list(aid=aid, test_type="pvt", limit=100):
        t = store.get(x["test_id"])
        m = (t["result"] or {}).get("metrics") or {}
        out.append({"id": x["test_id"], "test_id": x["test_id"], "mission_day": x["mission_day"], "status": x["status"],
                    "started_at": x["started_at"], "duration_s": x["duration_s"], "valid": bool(x["scored"]),
                    "stats": m, "source": f"session #{x['app_session']}" + (" (this session)"
                                                                          if x["app_session"] == rt().history.session else "")})
    return out


@app.post("/api/pvt/{aid}")
def pvt_submit(aid: str, req: PVTReq):
    return pvt(aid, req)


@app.get("/api/mission")
def mission():
    r = rt()
    with r.lock:
        e = r.engine
        return {"mission": e.mission.status(e.t), "t": e.t, "t0": e.baseline_end, "speed": r.speed, "paused": r.paused,
                "shelter": e.shelter, "spe_active": e.spe.active, "cabin": e.cabin_state, "log": list(e.log)[:60],
                "comms": e.comms.snapshot(), "sync": e.comms.stats(e.t)}


@app.get("/api/simulation")
def simulation():
    with rt().lock:
        return rt().sim.status()


class SimReq(BaseModel):
    scenario: str | None = None
    astronaut_id: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=60)


@app.post("/api/simulation/{action}")
def simulation_action(action: str, req: SimReq | None = None):
    r = rt()
    req = req or SimReq()
    if action == "reset":
        r.sim.reset()
        return r.sim.status()
    with r.lock:
        try:
            if action == "start":
                if not req.scenario:
                    raise HTTPException(400, "scenario required")
                return r.sim.start(req.scenario, req.astronaut_id, req.speed)
            if action in ("pause", "resume", "stop"):
                getattr(r.sim, action)()
                return r.sim.status()
            if action == "speed" and req.speed:
                r.speed = req.speed
                return r.sim.status()
        except KeyError as ex:
            raise HTTPException(400, f"unknown scenario {ex}") from ex
        except RuntimeError as ex:
            raise HTTPException(409, str(ex)) from ex
    raise HTTPException(400, f"unknown action '{action}'")


@app.get("/api/medical-guidance")
def medical_guidance(astronaut: str | None = None, region: str | None = None, incident: int | None = None,
                     concern: str | None = None):
    with rt().lock:
        e = rt().engine
        inc = _inc(incident) if incident is not None else None
        a = None if inc is not None and inc["astronaut_id"] not in e.by_id else (
            inc["astronaut_id"] if inc is not None else _aid(astronaut))
        try:
            return guidance.build(e, a, region=region, incident=inc, concern=concern)
        except KeyError as ex:
            raise HTTPException(400, f"unknown concern {ex}") from ex


@app.get("/api/medical-guidance/search")
def medical_guidance_search(q: str):
    with rt().lock:
        e = rt().engine
        protos = [{"id": p["id"], "title": p["title"], "score": round(s, 3), "steps": p["assessment_steps"],
                   "source": p["source"], "approval": p["approval"]} for p, s in e.kb.search(q, k=4)]
    return {"query": q, "concerns": guidance.search(q), "protocols": protos, "kb": guidance.kb_meta()}


@app.get("/api/system/status")
def system_status():
    import importlib.util
    r = rt()
    with r.lock:
        e = r.engine
        sh = e.system_health()
        store = None
        if e.store is not None:
            store = {"path": str(getattr(e.store, "path", "")), "integrity": sh.get("integrity", {}).get("store")}
        return {
            "offline_capable": True, "internet_required": False,
            "optional_network_features": ["NASA DONKI refresh (cached copy used offline)"],
            "local_inference": {"anomaly_model": e.anomaly.ready, "risk_forecaster": e.forecaster.ready,
                                "explanations": importlib.util.find_spec("shap") is not None,
                                "language_model": "none - core emergency system needs no LLM; assistant is retrieval-only"},
            "knowledge_base": {"protocols": e.kb.meta, "guidance": guidance.kb_meta()},
            "storage": store, "models": sh.get("models"), "sync": e.comms.stats(e.t),
            "runtime": {"tick_ms": round(r.tick_ms, 2), "speed": r.speed, "paused": r.paused,
                        "software_faults_contained": r.errors, "last_fault": r.last_error},
            "hardware_assumption": "single laptop-class CPU core, ~1 GB RAM for backend; 3D view needs WebGL "
                                   "(integrated GPU); measured engine tick ~ few ms per crew minute",
        }


# ------------------------------------------------------------------ desktop lifecycle, version, history
@app.get("/api/system/version")
def version():
    from ares import __version__
    return {"name": "ARES - Autonomous Risk Evaluation & Emergency Support", "version": __version__,
            "build": "desktop" if getattr(__import__("sys"), "frozen", False) else "source",
            "status": "Research prototype - not a medical device, not flight-certified"}


@app.get("/api/system/health")
def health_check():
    """Readiness for the desktop launcher: every component that must be up before the UI is shown."""
    from ares import __version__, startup_status
    from ares.paths import APP_ROOT, DATA_DIR
    r = rt()
    with r.lock:
        e = r.engine
        checks = {
            "database": e.store is not None,
            "history": r.history.db is not None,
            "test_records": getattr(r, "tests", None) is not None,
            "models": bool(e.anomaly.ready and e.forecaster.ready),
            "knowledge_base": len(e.kb.protocols) > 0,
            "anatomy": (APP_ROOT / "assets" / "anatomy" / "ares_body.glb").exists(),
            "interface": (WEB3D / "index.html").exists(),
            "clock": r.thread.is_alive(),
        }
        return {"ready": all(checks.values()), "checks": checks, "version": __version__, "session": r.history.session,
                "previous_session_unclean": r.history.previous_unclean, "recovery": r.recovery,
                "data_dir": str(DATA_DIR), "pid": os.getpid(), "stages": startup_status.read().get("stages", {}),
                "tests": None if getattr(r, "tests", None) is None else {
                    "migrations": r.tests.migrations, "recovered_interrupted": r.tests.recovered_interrupted,
                    **r.tests.counts()}, "tests_error": getattr(r, "tests_error", None)}


@app.post("/api/system/shutdown")
def shutdown(request: Request):
    """Called by the desktop launcher on exit. Saves everything, marks the session clean, then stops the server."""
    tok = os.environ.get("ARES_SHUTDOWN_TOKEN")
    if tok and request.headers.get("x-ares-shutdown") != tok:
        raise HTTPException(403, "shutdown token required")
    r = rt()
    r.shutdown()
    srv = getattr(app.state, "uvicorn_server", None)
    if srv is not None:
        srv.should_exit = True
    return {"ok": True, "saved": True}


@app.get("/api/history/sessions")
def history_sessions():
    return rt().history.sessions()


@app.get("/api/history/archive")
def history_archive(session: int | None = None):
    return rt().history.archive(session)


@app.get("/api/history/simulations")
def history_simulations():
    return rt().history.sim_runs()


def main():
    import uvicorn

    uvicorn.run(app, host=os.environ.get("ARES_HOST", "127.0.0.1"), port=int(os.environ.get("ARES_PORT", 8000)),
                log_level="warning")


if __name__ == "__main__":
    main()
