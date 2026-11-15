"""Startup progress written by the backend and read by the desktop splash screen (DATA_DIR/startup_status.json)."""

from __future__ import annotations

import json
import os
import time

from ares.paths import DATA_DIR

FILE = DATA_DIR / "startup_status.json"
_state: dict = {}


def mark(stage: str, state: str, detail: str = "") -> None:
    """stage: recovery | database | models | knowledge | anatomy | interface | server; state: running | ok | error."""
    _state[stage] = {"state": state, "detail": detail, "t": time.time()}
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "stages": _state}))
        os.replace(tmp, FILE)
    except OSError:
        pass


def read() -> dict:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}
