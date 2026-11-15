"""Backend process started by the ARES desktop launcher (never by the user).

    ARES.exe --backend --port 8765 --parent-pid 1234        (packaged)
    python -m ares.desktop_backend --port 8765 --parent-pid 1234   (source)

* binds to 127.0.0.1 only (no network exposure)
* logs to DATA_DIR/logs/backend.log (rotating)
* stops gracefully on POST /api/system/shutdown (token from ARES_SHUTDOWN_TOKEN)
* watchdog: if the launcher process disappears (crash, killed), the backend saves and exits by itself,
  so no orphaned background process is left behind
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import threading
import time


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259            # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def setup_logging() -> logging.Logger:
    from ares.paths import LOG_DIR, ensure_dirs
    ensure_dirs()
    h = logging.handlers.RotatingFileHandler(LOG_DIR / "backend.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = [h]
    if sys.stderr is None or sys.stdout is None:          # windowed build: no console streams
        sys.stdout = sys.stderr = open(LOG_DIR / "backend_console.log", "a", encoding="utf-8", buffering=1)
    return logging.getLogger("ares.backend")


def run(port: int, parent_pid: int = 0) -> int:
    log = setup_logging()
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    import uvicorn

    from ares.api import server as srv
    log.info("ARES backend starting on 127.0.0.1:%s (parent pid %s, data %s)", port, parent_pid, os.environ.get("ARES_DATA_DIR"))
    config = uvicorn.Config(srv.app, host="127.0.0.1", port=port, log_level="warning", access_log=False, log_config=None)
    server = uvicorn.Server(config)
    srv.app.state.uvicorn_server = server

    def watchdog():
        while not server.should_exit:
            if not pid_alive(parent_pid):
                log.warning("launcher (pid %s) is gone - saving and shutting down", parent_pid)
                try:
                    if srv.RT is not None:
                        srv.RT.shutdown()
                finally:
                    server.should_exit = True
                return
            time.sleep(1.0)
    if parent_pid:
        threading.Thread(target=watchdog, daemon=True, name="parent-watchdog").start()
    try:
        server.run()
    except Exception:  # noqa: BLE001
        log.exception("backend crashed")
        return 1
    finally:
        if srv.RT is not None and not srv.RT.shutdown_done:
            srv.RT.shutdown()
        log.info("ARES backend stopped cleanly")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="store_true", help="(packaged exe) run the backend instead of the window")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--parent-pid", type=int, default=0)
    a, _ = ap.parse_known_args(argv)
    return run(a.port, a.parent_pid)


if __name__ == "__main__":
    sys.exit(main())
