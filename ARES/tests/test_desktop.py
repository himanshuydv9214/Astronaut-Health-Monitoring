"""Desktop-app building blocks: data folder, single instance, port choice, startup recovery, session history."""
import os
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

import ares_desktop as d  # noqa: E402

from ares import persistence  # noqa: E402


def test_instance_lock_is_exclusive(tmp_path):
    a, b = d.InstanceLock(tmp_path / "ares.lock"), d.InstanceLock(tmp_path / "ares.lock")
    assert a.acquire()
    if sys.platform != "win32":          # flock is per open file description - a 2nd handle in-process is refused
        assert not b.acquire()
    a.release()
    assert b.acquire()
    b.release()


def test_port_conflict_falls_back_to_free_port():
    s = socket.socket()
    if sys.platform != "win32":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", d.PREFERRED_PORT))
        s.listen()
    except OSError:
        pytest.skip("preferred port already in use on this machine")
    try:
        assert not d.port_free(d.PREFERRED_PORT)
        p = d.choose_port()
        assert p != d.PREFERRED_PORT and d.port_free(p)
    finally:
        s.close()


def test_backend_command_is_loopback_only():
    src = (ROOT / "ares" / "desktop_backend.py").read_text()
    assert 'host="127.0.0.1"' in src and "0.0.0.0" not in src


def _db(path: Path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    con.close()


def test_startup_recovery_backs_up_and_restores(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "DATA_DIR", tmp_path)
    monkeypatch.setattr(persistence, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(persistence, "HISTORY_DB", tmp_path / "ares_history.db")
    monkeypatch.setattr(persistence, "LOCAL_DB", tmp_path / "ares_local.db")
    monkeypatch.setattr(persistence, "ensure_dirs", lambda: None)
    (tmp_path / "backups").mkdir()
    _db(tmp_path / "ares_history.db")
    r1 = persistence.startup_recovery()
    assert r1["backup"] and not r1["errors"]
    (tmp_path / "ares_history.db").write_bytes(b"\x00not a database\x00" * 500)
    import time
    time.sleep(1.1)                                              # next backup folder gets a new timestamp
    r2 = persistence.startup_recovery()
    assert r2["restored"] and r2["restored"][0]["file"] == "ares_history.db"
    assert sqlite3.connect(tmp_path / "ares_history.db").execute("SELECT x FROM t").fetchone() == (42,)
    assert any(p.name.startswith("corrupt-") for p in (tmp_path / "backups").iterdir())


def test_unclean_session_is_flagged(tmp_path):
    h1 = persistence.HistoryStore(path=tmp_path / "h.db", app_version="test")
    h1.db.close()                                                 # crash: end_session never called
    h2 = persistence.HistoryStore(path=tmp_path / "h.db", app_version="test")
    s = h2.sessions()
    prev = [x for x in s if x["id"] == 1][0]
    assert not prev["clean"]
    h2.end_session()
    h2.close()


def test_frozen_layout_resources_exist():
    for rel in ("desktop/splash.html", "desktop/about.html", "desktop/already_running.html", "desktop/assets/ares.ico",
                "desktop/assets/ares.png", "desktop/ares.spec", "desktop/installer.iss", "knowledge_base", "models"):
        assert (ROOT / rel).exists(), rel
