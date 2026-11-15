"""Test-result persistence inside ares_history.db.

Schema (version 2, created by migration - existing data is kept):

  astronaut_profiles  astronaut_id PK, name, role, age, preflight_json, first_seen, updated
  test_sessions       test_id PK, astronaut_id FK -> astronaut_profiles, app_session FK -> sessions,
                      test_name, test_type, status, started_at, completed_at, duration_s, mission_day, mission_minute,
                      config_json, data_source, created, updated
  test_trials         (test_id FK -> test_sessions, trial_no) PK, t_offset_ms, isi_ms, rt_ms, outcome, recorded_at
  test_results        test_id PK FK -> test_sessions, metrics_json, scored, score_json, baseline_json,
                      comparison_json, interpretation_json, assessment_json, saved

Statuses: in_progress (being taken; trials are saved as they happen), completed, stopped (ended early by the user),
terminated (aborted - e.g. Terminate button or window closed), interrupted (the app stopped while the test was
running - detected at the next start), legacy (saved before status tracking existed; status unknown).

Every write runs in a transaction; a result is reported as saved only after it has been committed and read back.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

SCHEMA_VERSION = 2
STATUSES = ("in_progress", "completed", "stopped", "terminated", "interrupted", "legacy")
FINAL_STATUSES = ("completed", "stopped", "terminated")
OUTCOMES = ("response", "lapse", "false_start", "miss", "premature")
TEST_TYPES = {
    "pvt": "Reaction time test (PVT-B)",
    "wellness_checkin": "Daily wellness check-in",
    "symptom_report": "Symptom report",
    "lab_panel": "Blood test entry",
}
STALE_MIN = 20          # an in_progress test with no activity for this long (same session) is marked interrupted


class StoreError(RuntimeError):
    pass


def _migrate(db: sqlite3.Connection) -> list[str]:
    """Bring ares_history.db to SCHEMA_VERSION. Idempotent; never drops data."""
    done = []
    v = db.execute("PRAGMA user_version").fetchone()[0]
    if v < 2:
        with db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS astronaut_profiles (
                astronaut_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, age INTEGER, preflight_json TEXT,
                first_seen REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS test_sessions (
                test_id TEXT PRIMARY KEY,
                astronaut_id TEXT NOT NULL REFERENCES astronaut_profiles(astronaut_id),
                app_session INTEGER REFERENCES sessions(id),
                test_name TEXT NOT NULL, test_type TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('in_progress','completed','stopped','terminated','interrupted','legacy')),
                started_at REAL NOT NULL, completed_at REAL, duration_s REAL, mission_day REAL, mission_minute REAL,
                config_json TEXT, data_source TEXT, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS test_trials (
                test_id TEXT NOT NULL REFERENCES test_sessions(test_id) ON DELETE CASCADE,
                trial_no INTEGER NOT NULL, t_offset_ms REAL, isi_ms REAL, rt_ms REAL,
                outcome TEXT NOT NULL CHECK (outcome IN ('response','lapse','false_start','miss','premature')),
                recorded_at REAL, PRIMARY KEY (test_id, trial_no));
            CREATE TABLE IF NOT EXISTS test_results (
                test_id TEXT PRIMARY KEY REFERENCES test_sessions(test_id) ON DELETE CASCADE,
                metrics_json TEXT, scored INTEGER, score_json TEXT, baseline_json TEXT, comparison_json TEXT,
                interpretation_json TEXT, assessment_json TEXT, saved REAL);
            CREATE INDEX IF NOT EXISTS ix_tests_astro_time ON test_sessions(astronaut_id, started_at);
            CREATE INDEX IF NOT EXISTS ix_tests_type_time ON test_sessions(test_type, started_at);
            CREATE INDEX IF NOT EXISTS ix_tests_status ON test_sessions(status);
            CREATE INDEX IF NOT EXISTS ix_trials_test ON test_trials(test_id);
            """)
            # carry over reaction tests saved by v0.4 (pvt_runs) so no earlier result is lost
            have_pvt = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pvt_runs'").fetchone()
            n = 0
            if have_pvt:
                for rid, sess, aid, saved, payload in db.execute(
                        "SELECT id, session, aid, saved, payload FROM pvt_runs ORDER BY id").fetchall():
                    tid = f"LEGACY-{rid:05d}"
                    if db.execute("SELECT 1 FROM test_sessions WHERE test_id=?", (tid,)).fetchone():
                        continue
                    try:
                        run = json.loads(payload)
                    except ValueError:
                        continue
                    db.execute("INSERT OR IGNORE INTO astronaut_profiles (astronaut_id, name, first_seen, updated) "
                               "VALUES (?,?,?,?)", (aid, aid, saved, saved))
                    stats = run.get("stats") or {}
                    dur = run.get("duration_s")
                    db.execute("INSERT INTO test_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (tid, aid, sess, TEST_TYPES["pvt"], "pvt", "legacy", saved - (dur or 0), saved, dur,
                                run.get("mission_day"), run.get("t"), json.dumps({"note": "migrated from v0.4"}),
                                run.get("source", "live (browser)"), saved, saved))
                    for i, rt in enumerate(stats.get("rts_ms") or [], 1):
                        oc = "false_start" if rt < 130 else "lapse" if rt >= 355 else "response"
                        db.execute("INSERT INTO test_trials VALUES (?,?,?,?,?,?,?)", (tid, i, None, None, rt, oc, saved))
                    db.execute("INSERT INTO test_results VALUES (?,?,?,?,?,?,?,?,?)",
                               (tid, json.dumps(stats), int(bool(run.get("valid"))), json.dumps(run.get("score")),
                                None, None, json.dumps([{"text": "Saved by ARES v0.4 before test status was recorded; "
                                                                 "whether this test ran to the end is unknown.",
                                                         "kind": "note"}]),
                                json.dumps(run.get("assessment")), saved))
                    n += 1
            db.execute("PRAGMA user_version=2")
        done.append(f"schema v2 (test sessions/trials/results/profiles); {n} earlier reaction test(s) migrated")
    return done


class TestStore:
    """Uses the HistoryStore's SQLite connection and lock (one database file, one writer)."""
    __test__ = False          # not a pytest test class

    def __init__(self, history):
        self.h = history
        self.db = history.db
        self.lock = history.lock
        self.db.execute("PRAGMA foreign_keys=ON")
        with self.lock:
            self.migrations = _migrate(self.db)
            # tests that were running when ARES stopped last time -> interrupted (never "completed")
            cur = self.db.execute(
                "UPDATE test_sessions SET status='interrupted', updated=?, completed_at=COALESCE("
                "(SELECT MAX(recorded_at) FROM test_trials tt WHERE tt.test_id=test_sessions.test_id), started_at) "
                "WHERE status='in_progress' AND (app_session IS NULL OR app_session<>?)", (time.time(), history.session))
            self.recovered_interrupted = cur.rowcount
            self.db.commit()
        self._results_for_interrupted()

    # ------------------------------------------------------------ profiles
    def upsert_profiles(self, crew) -> None:
        now = time.time()
        with self.lock, self.db:
            for p in crew:
                pre = {k: getattr(p, k) for k in ("hr", "hrv_rmssd", "spo2", "rr", "sbp", "dbp", "temp", "sleep_hours")
                       if hasattr(p, k)}
                self.db.execute(
                    "INSERT INTO astronaut_profiles VALUES (?,?,?,?,?,?,?) ON CONFLICT(astronaut_id) DO UPDATE SET "
                    "name=excluded.name, role=excluded.role, age=excluded.age, preflight_json=excluded.preflight_json, "
                    "updated=excluded.updated", (p.id, p.name, getattr(p, "role", None), getattr(p, "age", None),
                                                 json.dumps(pre), now, now))

    def profiles(self) -> dict[str, dict]:
        with self.lock:
            rows = self.db.execute("SELECT astronaut_id, name, role, age, preflight_json FROM astronaut_profiles").fetchall()
        return {r[0]: {"id": r[0], "name": r[1], "role": r[2], "age": r[3], "preflight": json.loads(r[4] or "{}")}
                for r in rows}

    # ------------------------------------------------------------ writes
    def create(self, aid: str, test_type: str, config: dict | None, mission_day: float | None,
               mission_minute: float | None, data_source: str, status: str = "in_progress",
               started_at: float | None = None) -> str:
        if test_type not in TEST_TYPES:
            raise StoreError(f"unknown test type {test_type}")
        if status not in STATUSES:
            raise StoreError(f"unknown status {status}")
        tid = f"T{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:10].upper()}"
        now = time.time()
        try:
            with self.lock, self.db:
                self.db.execute("INSERT INTO test_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (tid, aid, self.h.session, TEST_TYPES[test_type], test_type, status, started_at or now,
                                 None, None, mission_day, mission_minute, json.dumps(config or {}), data_source, now, now))
        except sqlite3.Error as ex:
            raise StoreError(f"could not create the test record: {ex}") from ex
        return tid

    def session(self, tid: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM test_sessions WHERE test_id=?", (tid,)).fetchone()
            cols = [d[0] for d in self.db.execute("SELECT * FROM test_sessions LIMIT 0").description]
        if not r:
            return None
        d = dict(zip(cols, r))
        d["config"] = json.loads(d.pop("config_json") or "{}")
        return d

    def add_trials(self, tid: str, trials: list[dict]) -> dict:
        """Append trials (idempotent: re-sent trial numbers are ignored). Only while the test is in progress."""
        s = self.session(tid)
        if s is None:
            raise StoreError("unknown test")
        if s["status"] != "in_progress":
            raise StoreError(f"test is already {s['status']}; trials can no longer be added")
        now = time.time()
        rows = []
        for t in trials:
            oc = t.get("outcome")
            if oc not in OUTCOMES:
                raise StoreError(f"invalid trial outcome {oc!r}")
            rt = t.get("rt_ms")
            if rt is not None and not (0 <= float(rt) <= 60000):
                raise StoreError(f"implausible reaction time {rt}")
            if oc in ("miss", "premature") and rt is not None:
                raise StoreError(f"a {oc} trial has no reaction time")
            rows.append((tid, int(t["trial_no"]), t.get("t_offset_ms"), t.get("isi_ms"),
                         None if rt is None else float(rt), oc, now))
        try:
            with self.lock, self.db:
                self.db.executemany("INSERT OR IGNORE INTO test_trials VALUES (?,?,?,?,?,?,?)", rows)
                self.db.execute("UPDATE test_sessions SET updated=? WHERE test_id=?", (now, tid))
                n = self.db.execute("SELECT COUNT(*) FROM test_trials WHERE test_id=?", (tid,)).fetchone()[0]
        except sqlite3.Error as ex:
            raise StoreError(f"could not save trials: {ex}") from ex
        return {"test_id": tid, "trials_saved": n}

    def trials(self, tid: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT trial_no, t_offset_ms, isi_ms, rt_ms, outcome, recorded_at FROM test_trials "
                                   "WHERE test_id=? ORDER BY trial_no", (tid,)).fetchall()
        return [{"trial_no": r[0], "t_offset_ms": r[1], "isi_ms": r[2], "rt_ms": r[3], "outcome": r[4],
                 "recorded_at": r[5]} for r in rows]

    def finish(self, tid: str, status: str, duration_s: float | None, result: dict) -> dict:
        """Close a test with its final status and results in ONE transaction; returns the verified record."""
        if status not in FINAL_STATUSES:
            raise StoreError(f"final status must be one of {FINAL_STATUSES}")
        s = self.session(tid)
        if s is None:
            raise StoreError("unknown test")
        if s["status"] != "in_progress":
            raise StoreError(f"test is already {s['status']}")
        now = time.time()
        try:
            with self.lock, self.db:
                self.db.execute("UPDATE test_sessions SET status=?, completed_at=?, duration_s=?, updated=? WHERE test_id=?",
                                (status, now, duration_s, now, tid))
                self.db.execute("INSERT OR REPLACE INTO test_results VALUES (?,?,?,?,?,?,?,?,?)",
                                (tid, json.dumps(result.get("metrics")), int(bool(result.get("scored"))),
                                 json.dumps(result.get("score")), json.dumps(result.get("baseline")),
                                 json.dumps(result.get("comparison")), json.dumps(result.get("interpretation")),
                                 json.dumps(result.get("assessment")), now))
        except sqlite3.Error as ex:
            raise StoreError(f"could not save the result: {ex}") from ex
        return self.verify(tid)

    def record_single(self, aid: str, test_type: str, mission_day, mission_minute, data_source: str,
                      config: dict | None, result: dict, status: str = "completed") -> dict:
        """One-step assessments (check-in, symptoms, labs): session + result in one transaction."""
        tid = f"T{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:10].upper()}"
        now = time.time()
        try:
            with self.lock, self.db:
                self.db.execute("INSERT INTO test_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (tid, aid, self.h.session, TEST_TYPES[test_type], test_type, status, now, now, 0.0,
                                 mission_day, mission_minute, json.dumps(config or {}), data_source, now, now))
                self.db.execute("INSERT INTO test_results VALUES (?,?,?,?,?,?,?,?,?)",
                                (tid, json.dumps(result.get("metrics")), int(bool(result.get("scored"))),
                                 json.dumps(result.get("score")), json.dumps(result.get("baseline")),
                                 json.dumps(result.get("comparison")), json.dumps(result.get("interpretation")),
                                 json.dumps(result.get("assessment")), now))
        except sqlite3.Error as ex:
            raise StoreError(f"could not save the assessment: {ex}") from ex
        return self.verify(tid)

    def verify(self, tid: str) -> dict:
        """Read back what was committed (the confirmation shown to the user is based on this)."""
        with self.lock:
            s = self.db.execute("SELECT status FROM test_sessions WHERE test_id=?", (tid,)).fetchone()
            r = self.db.execute("SELECT saved FROM test_results WHERE test_id=?", (tid,)).fetchone()
            n = self.db.execute("SELECT COUNT(*) FROM test_trials WHERE test_id=?", (tid,)).fetchone()[0]
        if not s or not r:
            raise StoreError("the result could not be read back after saving")
        return {"test_id": tid, "status": s[0], "trials_saved": n, "saved_at": r[0], "verified": True,
                "database": str(self.h.path)}

    def mark_stale(self) -> int:
        """Same-session tests abandoned without a final status (e.g. a browser tab closed) -> interrupted."""
        cutoff = time.time() - STALE_MIN * 60
        with self.lock, self.db:
            n = self.db.execute("UPDATE test_sessions SET status='interrupted', updated=? WHERE status='in_progress' "
                                "AND updated<?", (time.time(), cutoff)).rowcount
        if n:
            self._results_for_interrupted()
        return n

    def _results_for_interrupted(self) -> None:
        """Keep the partial results of interrupted tests (computed from the trials saved before the stop)."""
        from ares.assessments.analysis import pvt_metrics
        with self.lock:
            todo = [r[0] for r in self.db.execute(
                "SELECT s.test_id FROM test_sessions s LEFT JOIN test_results r ON r.test_id=s.test_id "
                "WHERE s.status='interrupted' AND r.test_id IS NULL AND s.test_type='pvt'").fetchall()]
        for tid in todo:
            tr = self.trials(tid)
            m = pvt_metrics(tr)
            with self.lock, self.db:
                first = self.db.execute("SELECT started_at, completed_at FROM test_sessions WHERE test_id=?",
                                        (tid,)).fetchone()
                dur = None if not first or not first[1] else round(max(0.0, first[1] - first[0]), 1)
                self.db.execute("UPDATE test_sessions SET duration_s=COALESCE(duration_s, ?) WHERE test_id=?", (dur, tid))
                self.db.execute("INSERT OR IGNORE INTO test_results VALUES (?,?,?,?,?,?,?,?,?)",
                                (tid, json.dumps(m), 0, None, None, None, json.dumps([{
                                    "kind": "status", "s": "watch",
                                    "text": f"ARES stopped while this test was running (interrupted). The {len(tr)} trial(s) "
                                            "saved before the stop are kept; the test is not scored and not used for the "
                                            "baseline."}]), None, time.time()))

    # ------------------------------------------------------------ reads
    def list(self, aid: str | None = None, test_type: str | None = None, status: str | None = None,
             date_from: float | None = None, date_to: float | None = None, limit: int = 500) -> list[dict]:
        q = ("SELECT s.test_id, s.astronaut_id, p.name, s.test_name, s.test_type, s.status, s.started_at, s.completed_at, "
             "s.duration_s, s.mission_day, s.data_source, s.app_session, r.metrics_json, r.scored, "
             "(SELECT COUNT(*) FROM test_trials t WHERE t.test_id=s.test_id) "
             "FROM test_sessions s LEFT JOIN astronaut_profiles p ON p.astronaut_id=s.astronaut_id "
             "LEFT JOIN test_results r ON r.test_id=s.test_id WHERE 1=1")
        args: list = []
        for cond, val in (("s.astronaut_id=?", aid), ("s.test_type=?", test_type), ("s.status=?", status),
                          ("s.started_at>=?", date_from), ("s.started_at<=?", date_to)):
            if val is not None and val != "":
                q += f" AND {cond}"
                args.append(val)
        q += " ORDER BY s.started_at DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        out = []
        for r in rows:
            m = json.loads(r[12]) if r[12] else None
            out.append({"test_id": r[0], "astronaut_id": r[1], "astronaut_name": r[2] or r[1], "test_name": r[3],
                        "test_type": r[4], "status": r[5], "started_at": r[6], "completed_at": r[7],
                        "duration_s": r[8], "mission_day": r[9], "data_source": r[10], "app_session": r[11],
                        "summary": summary_of(r[4], m), "scored": bool(r[13]) if r[13] is not None else None,
                        "trials": r[14]})
        return out

    def get(self, tid: str) -> dict | None:
        s = self.session(tid)
        if s is None:
            return None
        with self.lock:
            r = self.db.execute("SELECT metrics_json, scored, score_json, baseline_json, comparison_json, "
                                "interpretation_json, assessment_json, saved FROM test_results WHERE test_id=?",
                                (tid,)).fetchone()
            name = self.db.execute("SELECT name FROM astronaut_profiles WHERE astronaut_id=?",
                                   (s["astronaut_id"],)).fetchone()
        res = None
        if r:
            res = {"metrics": json.loads(r[0]) if r[0] else None, "scored": bool(r[1]),
                   "score": json.loads(r[2]) if r[2] else None, "baseline": json.loads(r[3]) if r[3] else None,
                   "comparison": json.loads(r[4]) if r[4] else None,
                   "interpretation": json.loads(r[5]) if r[5] else None,
                   "assessment": json.loads(r[6]) if r[6] else None, "saved_at": r[7]}
        return s | {"astronaut_name": name[0] if name else s["astronaut_id"], "result": res, "trials": self.trials(tid)}

    def counts(self) -> dict:
        with self.lock:
            return {"tests": self.db.execute("SELECT COUNT(*) FROM test_sessions").fetchone()[0],
                    "trials": self.db.execute("SELECT COUNT(*) FROM test_trials").fetchone()[0],
                    "by_status": dict(self.db.execute("SELECT status, COUNT(*) FROM test_sessions GROUP BY status"))}


def summary_of(test_type: str, m: dict | None) -> str:
    """One-line 'average result' for tables. Only metrics the test actually produced."""
    if not m:
        return "—"
    if test_type == "pvt":
        if m.get("mean_rt_ms") is None:
            return f"no valid responses ({m.get('trials', 0)} trials)"
        return f"{m['mean_rt_ms']:.0f} ms avg · {m.get('lapses', 0)} lapses"
    if test_type == "wellness_checkin":
        return f"fatigue {m.get('samn_perelli')}/7 · sleep {m.get('sleep_quality')}/10"
    if test_type == "symptom_report":
        s = m.get("symptoms") or []
        return ", ".join(x.replace("_", " ") for x in s) if s else "no symptoms"
    if test_type == "lab_panel":
        fl = m.get("flags") or []
        return f"{len(m.get('values', {}))} values · {len(fl)} flag(s)"
    return "—"
