"""Cross-session persistence, backups and recovery (desktop operation).

Two local SQLite files live in DATA_DIR:
  ares_local.db    minute vitals / events / behavioral rows with a tamper-evident hash chain (ares.storage)
  ares_history.db  what must survive closing ARES: sessions, reaction-time test results, incident archive
                   (report + workflow + timeline), simulation runs. Written immediately (PVT) or every 30 s and
                   at shutdown (incidents, simulation), so a crash loses at most ~30 s of workflow edits.

Startup recovery (run BEFORE the databases are opened):
  1. PRAGMA quick_check on each database.
  2. A database that fails is moved aside to backups/corrupt-<time>-<name> and the newest good backup is restored.
  3. A consistent copy (SQLite online backup API) of each good database is written to backups/<time>/ (5 kept).
A session that never recorded a clean shutdown is reported as "recovered after unexpected stop".
Restarting ARES never re-runs an emergency action: workflow steps are restored as history, never replayed.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from ares.paths import BACKUP_DIR, DATA_DIR, ensure_dirs

HISTORY_DB = DATA_DIR / "ares_history.db"
LOCAL_DB = DATA_DIR / "ares_local.db"
KEEP_BACKUPS = 5


# ------------------------------------------------------------------ integrity, backup, restore
def _quick_check(path: Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        ok = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        con.close()
        return ok
    except sqlite3.DatabaseError:
        return False


def _backup_copy(src: Path, dst: Path) -> None:
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    with d:
        s.backup(d)
    d.close()
    s.close()


def startup_recovery() -> dict:
    """Check, repair from backup if needed, then back up. Returns a report shown in the system status."""
    ensure_dirs()
    report = {"checked": [], "restored": [], "backup": None, "errors": []}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backups = sorted([p for p in BACKUP_DIR.iterdir() if p.is_dir() and p.name[:2] == "20"], reverse=True)
    for db in (LOCAL_DB, HISTORY_DB):
        if not db.exists():
            continue
        ok = _quick_check(db)
        report["checked"].append({"file": db.name, "ok": ok})
        if ok:
            continue
        bad = BACKUP_DIR / f"corrupt-{stamp}-{db.name}"
        shutil.move(str(db), bad)
        for side in (db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            if side.exists():
                shutil.move(str(side), BACKUP_DIR / f"corrupt-{stamp}-{side.name}")
        src = next((b / db.name for b in backups if (b / db.name).exists() and _quick_check(b / db.name)), None)
        if src:
            shutil.copy2(src, db)
            report["restored"].append({"file": db.name, "from": src.parent.name, "corrupt_copy": bad.name})
        else:
            report["errors"].append(f"{db.name} was damaged and no good backup existed; a new empty database is used "
                                    f"(damaged copy kept as {bad.name})")
    try:
        target = BACKUP_DIR / stamp
        made = False
        for db in (LOCAL_DB, HISTORY_DB):
            if db.exists():
                target.mkdir(exist_ok=True)
                _backup_copy(db, target / db.name)
                made = True
        if made:
            report["backup"] = target.name
        for old in sorted([p for p in BACKUP_DIR.iterdir() if p.is_dir() and p.name[:2] == "20"])[:-KEEP_BACKUPS]:
            shutil.rmtree(old, ignore_errors=True)
    except (OSError, sqlite3.Error) as ex:
        report["errors"].append(f"backup failed: {ex}")
    return report


# ------------------------------------------------------------------ history store
class HistoryStore:
    def __init__(self, path: Path = HISTORY_DB, app_version: str = "?"):
        ensure_dirs()
        self.path = Path(path)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, started REAL, ended REAL, clean INTEGER DEFAULT 0,
                version TEXT, note TEXT);
            CREATE TABLE IF NOT EXISTS pvt_runs (id INTEGER PRIMARY KEY, session INTEGER, aid TEXT, saved REAL, payload TEXT);
            CREATE TABLE IF NOT EXISTS incidents (session INTEGER, gen INTEGER, inc_id INTEGER, aid TEXT, opened REAL,
                level INTEGER, status TEXT, saved REAL, payload TEXT, PRIMARY KEY (session, gen, inc_id));
            CREATE TABLE IF NOT EXISTS sim_runs (session INTEGER, started REAL, scenario TEXT, state TEXT, saved REAL,
                payload TEXT, PRIMARY KEY (session, started));
        """)
        prev = self.db.execute("SELECT id, clean FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        self.previous_unclean = bool(prev and not prev[1])
        if self.previous_unclean:
            self.db.execute("UPDATE sessions SET note=? WHERE id=?", ("ended unexpectedly (crash or power loss)", prev[0]))
        self.session = self.db.execute("INSERT INTO sessions (started, version) VALUES (?, ?)",
                                       (time.time(), app_version)).lastrowid
        self.db.commit()

    # ---------------------------------------------------------------- writes
    def save_pvt(self, aid: str, run: dict) -> None:
        with self.lock:
            self.db.execute("INSERT INTO pvt_runs (session, aid, saved, payload) VALUES (?,?,?,?)",
                            (self.session, aid, time.time(), json.dumps(run, default=str)))
            self.db.commit()

    def save_incidents(self, engine, status_of, gen: int = 0) -> int:
        rows = []
        for inc in engine.incidents.values():
            p = {k: v for k, v in inc.items() if k != "history"} | {"history": [list(h) for h in inc["history"]]}
            rows.append((self.session, gen, inc["id"], inc["astronaut_id"], inc["opened"], inc["level"], status_of(inc),
                         time.time(), json.dumps(p, default=str)))
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?)", rows)
            self.db.commit()
        return len(rows)

    def save_sim(self, sim_status: dict, started: float | None) -> None:
        if started is None or not sim_status.get("scenario"):
            return
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO sim_runs VALUES (?,?,?,?,?,?)",
                            (self.session, started, sim_status["scenario"], sim_status["state"], time.time(),
                             json.dumps({k: sim_status[k] for k in ("title", "target_name", "elapsed_min", "events")},
                                        default=str)))
            self.db.commit()

    def end_session(self) -> None:
        with self.lock:
            self.db.execute("UPDATE sessions SET ended=?, clean=1 WHERE id=?", (time.time(), self.session))
            self.db.commit()

    def close(self) -> None:
        with self.lock:
            try:
                self.db.commit()
                self.db.close()
            except sqlite3.ProgrammingError:
                pass

    # ---------------------------------------------------------------- reads
    def previous_pvt_runs(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        with self.lock:
            for aid, payload, sess in self.db.execute(
                    "SELECT aid, payload, session FROM pvt_runs WHERE session < ? ORDER BY id", (self.session,)):
                r = json.loads(payload) | {"source": f"earlier session #{sess}"}
                out.setdefault(aid, []).append(r)
        return out

    def sessions(self, limit: int = 20) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id, started, ended, clean, version, note FROM sessions ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()
            counts = dict(self.db.execute("SELECT session, COUNT(*) FROM incidents GROUP BY session").fetchall())
            pvts = dict(self.db.execute("SELECT session, COUNT(*) FROM pvt_runs GROUP BY session").fetchall())
        return [{"id": r[0], "started": r[1], "ended": r[2], "clean": bool(r[3]), "version": r[4], "note": r[5],
                 "current": r[0] == self.session, "incidents": counts.get(r[0], 0), "pvt_runs": pvts.get(r[0], 0)}
                for r in rows]

    def archive(self, session: int | None = None, limit: int = 200) -> list[dict]:
        q = "SELECT session, gen, inc_id, aid, opened, level, status, payload FROM incidents"
        args: tuple = ()
        if session is not None:
            q += " WHERE session=?"
            args = (session,)
        q += " ORDER BY session DESC, opened DESC LIMIT ?"
        with self.lock:
            rows = self.db.execute(q, args + (limit,)).fetchall()
        out = []
        for s, g, i, aid, opened, lvl, status, payload in rows:
            p = json.loads(payload)
            rep = p.get("report") or {}
            out.append({"session": s, "run": g, "id": i, "astronaut_id": aid, "opened": opened, "level": lvl, "status": status,
                        "peak_level": p.get("peak_level"), "event": rep.get("event"),
                        "workflow_events": (p.get("wf") or {}).get("events", []), "reasons": rep.get("reasons", [])[:6]})
        return out

    def sim_runs(self, limit: int = 30) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT session, started, scenario, state, payload FROM sim_runs "
                                   "ORDER BY saved DESC LIMIT ?", (limit,)).fetchall()
        return [{"session": s, "started": st, "scenario": sc, "state": state} | json.loads(p) for s, st, sc, state, p in rows]
