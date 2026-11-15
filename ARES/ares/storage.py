"""Offline-first local storage with tamper-evident integrity.

SQLite (single file, no server, survives restarts) holds minute summaries,
incidents, the comm log and behavioral records. Every row carries
    hash = SHA-256(previous_hash || canonical JSON of the row)
forming a hash chain per table, so any later edit or deletion of health
records is detectable (`verify()`), which matters when the record will be
synchronised to Earth hours later and used for medical decisions.

Health data handling: the file stays on the vehicle; only prioritised
summaries are queued for Earth (see mission.comms). Encryption at rest
(e.g., SQLCipher) is noted as a deployment requirement, not implemented here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

from ares.paths import DATA_DIR

DB_PATH = DATA_DIR / "ares_local.db"
TABLES = ("vitals", "events", "behavioral")


class LocalStore:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")       # crash / power-loss safe, readers never block the writer
        self.db.execute("PRAGMA synchronous=NORMAL")
        for t in TABLES:
            self.db.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY, t REAL, aid TEXT, "
                            f"payload TEXT, prev TEXT, hash TEXT)")
        self.db.commit()
        self._last = {t: self._tail(t) for t in TABLES}

    def _tail(self, table: str) -> str:
        r = self.db.execute(f"SELECT hash FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
        return r[0] if r else "GENESIS"

    @staticmethod
    def _h(prev: str, t: float, aid: str, payload: str) -> str:
        # canonical time format: SQLite returns REAL, so 0 and 0.0 must hash identically
        return hashlib.sha256(f"{prev}|{float(t):.4f}|{aid}|{payload}".encode()).hexdigest()

    def append(self, table: str, t: float, aid: str, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        with self.lock:
            prev = self._last[table]
            h = self._h(prev, t, aid, body)
            self.db.execute(f"INSERT INTO {table} (t, aid, payload, prev, hash) VALUES (?,?,?,?,?)",
                            (t, aid, body, prev, h))
            self._last[table] = h

    def commit(self) -> None:
        with self.lock:
            self.db.commit()

    def verify(self) -> dict:
        out = {}
        with self.lock:
            for t in TABLES:
                prev, n, bad = "GENESIS", 0, None
                for rid, tt, aid, payload, p, h in self.db.execute(
                        f"SELECT id, t, aid, payload, prev, hash FROM {t} ORDER BY id"):
                    n += 1
                    if p != prev or self._h(prev, tt, aid, payload) != h:
                        bad = rid
                        break
                    prev = h
                out[t] = {"rows": n, "intact": bad is None, "first_bad_row": bad}
        return out

    def close(self) -> None:
        """Commit and close (called on graceful shutdown so no transaction is left in the journal)."""
        with self.lock:
            try:
                self.db.commit()
                self.db.close()
            except sqlite3.ProgrammingError:
                pass

    def counts(self) -> dict:
        with self.lock:
            return {t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
