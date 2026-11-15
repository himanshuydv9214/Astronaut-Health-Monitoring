"""Where ARES reads bundled resources and where it writes data.

APP_ROOT  read-only resources shipped with the app (models, knowledge base, built UI, 3D anatomy, reference data).
          Source checkout: the repository root. PyInstaller bundle: the bundle's resource folder.
DATA_DIR  writable data (SQLite databases, backups, logs, caches). Set by the desktop launcher through
          ARES_DATA_DIR (installed app: %LOCALAPPDATA%\\ARES\\data, portable app: .\\data next to ARES.exe).
          Default for a source checkout: <repo>/data, exactly as before.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
DATA_DIR = Path(os.environ.get("ARES_DATA_DIR") or (APP_ROOT / "data"))
LOG_DIR = DATA_DIR / "logs"
BACKUP_DIR = DATA_DIR / "backups"


def ensure_dirs() -> None:
    for d in (DATA_DIR, LOG_DIR, BACKUP_DIR, DATA_DIR / "cache"):
        d.mkdir(parents=True, exist_ok=True)
