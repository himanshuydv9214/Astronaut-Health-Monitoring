"""Test-result API: every astronaut test is saved permanently in the local database (works fully offline).

PVT flow (the React app):   POST /api/tests/sessions            -> test_id (status in_progress)
                            POST /api/tests/sessions/{id}/trials -> trials saved as they happen (incremental)
                            POST /api/tests/sessions/{id}/finish -> completed | stopped | terminated, results saved
A test left in_progress when ARES stops is marked "interrupted" at the next start.
Check-ins, symptom reports and lab entries are saved by their existing endpoints (see server.py).
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from ares.assessments import analysis
from ares.assessments.export import list_csv, test_csv, test_pdf
from ares.assessments.store import FINAL_STATUSES, OUTCOMES, STATUSES, TEST_TYPES, StoreError
from ares.behavioral.pvt import DURATION_S, ISI_RANGE_S, LAPSE_MS, FALSE_START_MS, score_pvt

router = APIRouter()
LIVE = "live test on this computer"
_rt = None


def bind(runtime_getter):
    global _rt
    _rt = runtime_getter


def rt():
    return _rt()


class StartReq(BaseModel):
    astronaut_id: str
    test_type: str = "pvt"
    config: dict | None = None


class TrialIn(BaseModel):
    trial_no: int = Field(ge=1, le=2000)
    outcome: str
    rt_ms: float | None = Field(default=None, ge=0, le=60000)
    isi_ms: float | None = Field(default=None, ge=0, le=60000)
    t_offset_ms: float | None = Field(default=None, ge=0, le=3_600_000)


class TrialsReq(BaseModel):
    trials: list[TrialIn] = Field(max_length=500)


class FinishReq(BaseModel):
    status: str
    duration_s: float | None = Field(default=None, ge=0, le=3600)
    trials: list[TrialIn] | None = Field(default=None, max_length=500)    # any not yet sent


def _store():
    t = getattr(rt(), "tests", None)
    if t is None:
        raise HTTPException(503, "test database unavailable - results cannot be saved")
    return t


def _mission(r):
    e = r.engine
    return round(e.mission.status(e.t)["mission_day"], 3), e.t


def finalize_pvt(r, tid: str, status: str, duration_s: float | None) -> dict:
    """Compute results from the STORED trials, update the twin / readiness model (completed tests only), save."""
    store = r.tests
    s = store.session(tid)
    trials = store.trials(tid)
    m = analysis.pvt_metrics(trials)
    rts = [t["rt_ms"] for t in trials if t["rt_ms"] is not None]
    prem = m["premature_no_stimulus"]
    e = r.engine
    assessment = None
    if status == "completed":
        res = e.submit_pvt(s["astronaut_id"], rts, prem, m["misses"], duration_s, m["trials"])
        score = res.get("result")
        scored = bool(res.get("ok"))
        if scored:
            assessment = {"category": analysis.MODEL, "level": res["assessment"]["level"],
                          "label": res["assessment"]["label"], "flagged": res["assessment"].get("flagged", [])}
    else:
        score = score_pvt(rts, prem) if rts else {"valid": False, "reason": "no responses"}
        scored = False
        e.twins[s["astronaut_id"]].add_event(e.t, "pvt", f"Reaction-time test {status} after {len(trials)} trial(s) "
                                             "- kept in the record, not scored", 0)
    baseline = analysis.baseline_for(store, s["astronaut_id"], "pvt", exclude=tid)
    previous = analysis.previous_for(store, s["astronaut_id"], "pvt", s["started_at"] + 1e-6, tid)
    comparison = {"baseline": analysis.compare(m, baseline.get("values")),
                  "previous": analysis.compare(m, previous["metrics"] if previous else None),
                  "previous_test": None if not previous else {k: previous[k] for k in ("test_id", "started_at", "mission_day")}}
    interp = analysis.interpret_pvt(m, status, baseline, previous, scored)
    return store.finish(tid, status, duration_s, {"metrics": m, "scored": scored, "score": score, "baseline": baseline,
                                                  "comparison": comparison, "interpretation": interp,
                                                  "assessment": assessment})


# ------------------------------------------------------------------ PVT sessions
@router.post("/api/tests/sessions")
def start(req: StartReq):
    r = rt()
    store = _store()
    if req.astronaut_id not in r.engine.by_id:
        raise HTTPException(404, "unknown astronaut")
    if req.test_type != "pvt":
        raise HTTPException(400, "only reaction tests are started as sessions; other assessments save in one step")
    cfg = {"protocol": "PVT-B", "planned_duration_s": DURATION_S, "isi_range_s": list(ISI_RANGE_S),
           "lapse_ms": LAPSE_MS, "false_start_ms": FALSE_START_MS, "miss_ms": 10000} | (req.config or {})
    with r.lock:
        day, minute = _mission(r)
    try:
        tid = store.create(req.astronaut_id, "pvt", cfg, day, minute, LIVE)
    except StoreError as ex:
        raise HTTPException(500, str(ex)) from ex
    return {"test_id": tid, "status": "in_progress", "config": cfg}


@router.post("/api/tests/sessions/{tid}/trials")
def add_trials(tid: str, req: TrialsReq):
    for t in req.trials:
        if t.outcome not in OUTCOMES:
            raise HTTPException(400, f"invalid outcome {t.outcome}")
    try:
        return _store().add_trials(tid, [t.model_dump() for t in req.trials])
    except StoreError as ex:
        raise HTTPException(409 if "already" in str(ex) else 400 if "invalid" in str(ex) or "implausible" in str(ex)
                            or "no reaction" in str(ex) or "unknown" in str(ex) else 500, str(ex)) from ex


def _finish(tid: str, req: FinishReq) -> dict:
    r = rt()
    store = _store()
    if req.status not in FINAL_STATUSES:
        raise HTTPException(400, f"status must be one of {FINAL_STATUSES}")
    s = store.session(tid)
    if s is None:
        raise HTTPException(404, "unknown test")
    if s["status"] == "interrupted":
        raise HTTPException(409, "this test was interrupted (ARES stopped while it ran); it is kept as interrupted "
                                 "with the trials saved before the stop")
    if s["status"] != "in_progress":
        # finishing twice (e.g. a retried request) returns the saved record instead of creating a duplicate
        return {"ok": True, "already_saved": True, "persisted": store.verify(tid), "test": store.get(tid)}
    try:
        if req.trials:
            store.add_trials(tid, [t.model_dump() for t in req.trials])
        with r.lock:
            persisted = finalize_pvt(r, tid, req.status, req.duration_s)
    except StoreError as ex:
        raise HTTPException(500, f"not saved: {ex}") from ex
    return {"ok": True, "persisted": persisted, "test": store.get(tid)}


@router.post("/api/tests/sessions/{tid}/finish")
def finish(tid: str, req: FinishReq):
    return _finish(tid, req)


@router.post("/api/tests/sessions/{tid}/beacon")
async def beacon(tid: str, request: Request):
    """navigator.sendBeacon target when the window/page closes mid-test (text/plain body)."""
    try:
        body = json.loads((await request.body()) or b"{}")
        req = FinishReq(**body)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(400, f"bad beacon: {ex}") from ex
    return _finish(tid, req)


# ------------------------------------------------------------------ history, details, exports, trends
@router.get("/api/tests")
def list_tests(astronaut: str | None = None, test_type: str | None = None, status: str | None = None,
               date_from: float | None = None, date_to: float | None = None, limit: int = 500):
    store = _store()
    store.mark_stale()
    if status and status not in STATUSES:
        raise HTTPException(400, "unknown status")
    rows = store.list(astronaut, test_type, status, date_from, date_to, min(limit, 2000))
    return {"tests": rows, "types": TEST_TYPES, "statuses": list(STATUSES), "counts": store.counts(),
            "astronauts": [{"id": p["id"], "name": p["name"]} for p in store.profiles().values()]}


@router.get("/api/tests/export.csv")
def export_list(astronaut: str | None = None, test_type: str | None = None, status: str | None = None,
                date_from: float | None = None, date_to: float | None = None):
    rows = _store().list(astronaut, test_type, status, date_from, date_to, 5000)
    return PlainTextResponse(list_csv(rows), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="ARES_test_history_{time.strftime("%Y%m%d_%H%M")}.csv"'})


@router.get("/api/tests/trends")
def trends(astronaut: str):
    r = rt()
    if astronaut not in r.engine.by_id:
        raise HTTPException(404, "unknown astronaut")
    with r.lock:
        return analysis.trends(_store(), astronaut, r.engine)


@router.get("/api/tests/{tid}")
def detail(tid: str):
    store = _store()
    t = store.get(tid)
    if t is None:
        raise HTTPException(404, "unknown test")
    hist = []
    if t["test_type"] == "pvt":
        for x in store.list(aid=t["astronaut_id"], test_type="pvt", limit=60):
            hist.append(x)
    return t | {"history": hist[::-1]}


@router.get("/api/tests/{tid}/export.csv")
def export_one(tid: str):
    t = _store().get(tid)
    if t is None:
        raise HTTPException(404, "unknown test")
    return PlainTextResponse(test_csv(t), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="ARES_test_{tid}.csv"'})


@router.get("/api/tests/{tid}/export.pdf")
def export_pdf(tid: str):
    r = rt()
    store = _store()
    t = store.get(tid)
    if t is None:
        raise HTTPException(404, "unknown test")
    tr = analysis.trends(store, t["astronaut_id"]) if t["test_type"] == "pvt" else None
    try:
        pdf = test_pdf(t, tr)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(500, f"PDF could not be created: {ex}") from ex
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="ARES_test_{tid}.pdf"'})


# ------------------------------------------------------------------ one-step assessments (called by server.py)
def save_single(r, aid: str, test_type: str, config: dict | None, metrics: dict, assessment: dict | None = None,
                interpretation: list | None = None) -> dict:
    store = getattr(r, "tests", None)
    if store is None:
        return {"verified": False, "error": "test database unavailable"}
    day, minute = _mission(r)
    try:
        return store.record_single(aid, test_type, day, minute, LIVE, config,
                                   {"metrics": metrics, "scored": True, "assessment": assessment,
                                    "interpretation": interpretation})
    except StoreError as ex:
        return {"verified": False, "error": str(ex)}


def save_legacy_pvt(r, aid: str, rts_ms: list[float], anticipations: int, misses: int,
                    duration_s: float | None, status: str) -> dict:
    """Old one-shot endpoints (classic dashboard): stored as a full test record with trials."""
    store = r.tests
    day, minute = _mission(r)
    tid = store.create(aid, "pvt", {"protocol": "PVT-B", "client": "classic dashboard / one-shot API",
                                    "note": "submitted at the end of the test; missed stimuli are listed last because "
                                            "their position in the sequence was not reported"}, day, minute, LIVE,
                       started_at=time.time() - (duration_s or 0))
    trials, n = [], 0
    for x in rts_ms:
        n += 1
        trials.append({"trial_no": n, "rt_ms": x, "outcome": "false_start" if x < FALSE_START_MS else
                       "lapse" if x >= LAPSE_MS else "response"})
    for _ in range(misses):
        n += 1
        trials.append({"trial_no": n, "rt_ms": None, "outcome": "miss"})
    for _ in range(anticipations):
        n += 1
        trials.append({"trial_no": n, "rt_ms": None, "outcome": "premature"})
    if trials:
        store.add_trials(tid, trials)
    return finalize_pvt(r, tid, status, duration_s)
