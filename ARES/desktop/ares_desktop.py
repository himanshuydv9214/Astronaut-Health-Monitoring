"""ARES desktop application launcher (pywebview + system WebView2/WebKit/Qt WebEngine).

Double-click ARES (installed shortcut, portable ARES.exe, or the dev shortcut) and this:
  1. enforces a single running instance (OS file lock in the data folder)
  2. picks a free local port (prefers 8765; never listens beyond 127.0.0.1)
  3. starts the Python backend as a hidden child process (no console window)
  4. shows a startup screen with live status (recovery/backup, database, AI models, knowledge base, 3D anatomy, UI)
  5. opens the ARES interface in a native window once every component reports ready
  6. supervises the backend: an unexpected exit is logged and restarted (max 3 times in 10 min); nothing is
     replayed - a restart never repeats an emergency action
  7. on exit (with confirmation) asks the backend to save and stop, then makes sure no process is left behind

Modes:  ARES.exe                 normal desktop app
        ARES.exe --backend ...   (internal) backend process
        ARES.exe --self-test     headless lifecycle test: start, check every component, shut down, print report
        ARES.exe --headless      backend + supervisor without a window (tests); Ctrl+C / SIGTERM stops cleanly
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
EXE_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[1]
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))      # bundled desktop resources
DESK_DIR = RES_DIR / "desktop" if FROZEN else Path(__file__).resolve().parent
APP_TITLE = "ARES — Astronaut Health Command"
PREFERRED_PORT = 8765
STAGES = ["recovery", "database", "models", "knowledge", "anatomy", "interface", "server"]


# ------------------------------------------------------------------ locations
def resolve_data_dir() -> Path:
    if os.environ.get("ARES_DATA_DIR"):
        return Path(os.environ["ARES_DATA_DIR"])
    if FROZEN and (EXE_DIR / "portable.flag").exists():              # portable build: data travels with the app
        return EXE_DIR / "data"
    if not FROZEN:                                                   # source checkout: keep using <repo>/data
        return EXE_DIR / "data"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ARES" / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ARES" / "data"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ARES" / "data"


DATA_DIR = resolve_data_dir()
LOG_DIR = DATA_DIR / "logs"


def app_version() -> str:
    try:
        sys.path.insert(0, str(EXE_DIR))
        from ares import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "?"


def setup_log() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(LOG_DIR / "desktop.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    lg = logging.getLogger("ares.desktop")
    lg.setLevel(logging.INFO)
    lg.addHandler(h)
    if FROZEN and (sys.stdout is None or sys.stderr is None):
        sys.stdout = sys.stderr = open(LOG_DIR / "desktop_console.log", "a", encoding="utf-8", buffering=1)
    return lg


# ------------------------------------------------------------------ single instance (released by the OS if we die)
class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False

    def release(self) -> None:
        if self.fh:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self.fh.close()
            self.fh = None


def port_free(port: int) -> bool:
    """True if nothing is listening on 127.0.0.1:port. Same socket rules as uvicorn, so a port that only has
    connections lingering from the previous run (TIME_WAIT) still counts as free on Linux/macOS; on Windows
    SO_EXCLUSIVEADDRUSE makes sure we never share a port with another program."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform == "win32":
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_port() -> int:
    if port_free(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:      # port conflict: let the OS pick a free one
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ backend supervision
class Backend:
    MAX_RESTARTS = 3
    WINDOW_S = 600

    def __init__(self, log: logging.Logger):
        self.log = log
        self.port = choose_port()
        self.token = secrets.token_hex(16)
        self.proc: subprocess.Popen | None = None
        self.stopping = False
        self.restarts: list[float] = []
        self.state = "starting"          # starting | ready | restarting | failed | stopped
        self.error: str | None = None
        self.health: dict = {}
        self.on_restarted = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _cmd(self) -> list[str]:
        if FROZEN:
            return [sys.executable, "--backend", "--port", str(self.port), "--parent-pid", str(os.getpid())]
        return [sys.executable, "-m", "ares.desktop_backend", "--port", str(self.port), "--parent-pid", str(os.getpid())]

    def start(self) -> None:
        env = os.environ.copy()
        env.update({"ARES_DATA_DIR": str(DATA_DIR), "ARES_SHUTDOWN_TOKEN": self.token, "OMP_NUM_THREADS": "1",
                    "PYTHONUNBUFFERED": "1"})
        flags = 0x08000000 if sys.platform == "win32" else 0                # CREATE_NO_WINDOW: never a console
        try:
            (DATA_DIR / "startup_status.json").unlink(missing_ok=True)
        except OSError:
            pass
        self.log.info("starting backend: %s (port %s)", " ".join(self._cmd()), self.port)
        self.proc = subprocess.Popen(self._cmd(), cwd=str(EXE_DIR), env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)

    def get(self, path: str, timeout: float = 2.0) -> dict:
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return json.loads(r.read())

    def wait_ready(self, timeout_s: float = 240) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if self.proc and self.proc.poll() is not None:
                self.error = f"the backend stopped during startup (exit code {self.proc.returncode})"
                return False
            try:
                self.health = self.get("/api/system/health")
                if self.health.get("ready"):
                    self.state = "ready"
                    return True
                bad = [k for k, v in self.health.get("checks", {}).items() if not v]
                if bad and time.time() - t0 > 20:
                    self.error = "component(s) not ready: " + ", ".join(bad)
            except Exception:  # noqa: BLE001 - not listening yet
                pass
            time.sleep(0.4)
        self.error = self.error or f"the backend did not become ready within {timeout_s:.0f} s"
        return False

    def stages(self) -> dict:
        try:
            return json.loads((DATA_DIR / "startup_status.json").read_text()).get("stages", {})
        except (OSError, ValueError):
            return {}

    def supervise(self) -> None:
        while not self.stopping:
            time.sleep(1.0)
            if self.stopping or self.proc is None or self.proc.poll() is None:
                continue
            code = self.proc.returncode
            self.log.error("backend exited unexpectedly (code %s)", code)
            now = time.time()
            self.restarts = [t for t in self.restarts if now - t < self.WINDOW_S]
            if len(self.restarts) >= self.MAX_RESTARTS:
                self.state, self.error = "failed", (f"the backend stopped {self.MAX_RESTARTS + 1} times in 10 minutes "
                                                    f"(last exit code {code}); see the logs")
                self.log.error(self.error)
                return
            self.restarts.append(now)
            self.state = "restarting"
            time.sleep(min(10, 2 * len(self.restarts)))
            if not port_free(self.port):
                time.sleep(2)
            self.start()
            if self.wait_ready(180):
                self.log.info("backend recovered (restart %s); data reloaded from the local databases, "
                              "no emergency action was repeated", len(self.restarts))
                if self.on_restarted:
                    self.on_restarted()
            else:
                self.log.error("backend restart failed: %s", self.error)

    def stop(self) -> None:
        self.stopping = True
        self.state = "stopped"
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            req = urllib.request.Request(self.url + "/api/system/shutdown", data=b"{}", method="POST",
                                         headers={"x-ares-shutdown": self.token, "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
            self.log.info("backend saved its data and is stopping")
        except Exception as ex:  # noqa: BLE001
            self.log.warning("graceful shutdown request failed: %s", ex)
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.log.warning("backend did not exit in time - terminating")
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.info("backend stopped (exit code %s)", self.proc.returncode)


def open_folder(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(p))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ------------------------------------------------------------------ the window
class Api:
    """Functions the startup screen and the interface can call (window.pywebview.api.*)."""

    def __init__(self, app: "DesktopApp"):
        self._app = app

    def status(self) -> dict:
        b = self._app.backend
        return {"state": b.state if b else "starting", "error": (b.error if b else self._app.error),
                "stages": b.stages() if b else {}, "version": self._app.version, "log_dir": str(LOG_DIR),
                "data_dir": str(DATA_DIR), "port": b.port if b else None}

    def open_logs(self) -> None:
        open_folder(LOG_DIR)

    def open_data(self) -> None:
        open_folder(DATA_DIR)

    def retry(self) -> None:
        threading.Thread(target=self._app.boot, daemon=True).start()

    def quit(self) -> None:
        self._app.window.destroy()

    def toggle_fullscreen(self) -> None:
        self._app.window.toggle_fullscreen()


class DesktopApp:
    def __init__(self):
        self.log = setup_log()
        self.version = app_version()
        self.backend: Backend | None = None
        self.window = None
        self.error: str | None = None
        self.booting = threading.Lock()
        self.notice: str | None = None

    def _set_notice_from_health(self, restarted: bool = False) -> None:
        h = self.backend.health if self.backend else {}
        if restarted:
            self.notice = ("ARES restarted its background service after an unexpected stop. Monitoring has resumed; "
                           "everything recorded was kept. Emergencies that were open are in Data &amp; System &rarr; history "
                           "and no action was repeated automatically - review them before acting.")
        elif h.get("previous_session_unclean"):
            restored = (h.get("recovery") or {}).get("restored")
            self.notice = ("ARES was not closed normally last time (crash or power loss). Local data was checked"
                           + (" and restored from the latest backup" if restored else " and is intact")
                           + ". Emergencies from that session are in the history; no action was repeated automatically.")

    def boot(self) -> None:
        if not self.booting.acquire(blocking=False):
            return
        try:
            if self.backend and self.backend.proc and self.backend.proc.poll() is None:
                self.backend.stop()
            self.backend = Backend(self.log)
            self.backend.on_restarted = self._restarted
            self.backend.start()
            if self.backend.wait_ready():
                self.log.info("ARES ready at %s", self.backend.url)
                self._set_notice_from_health()
                time.sleep(0.6)                      # let the splash show every green tick
                self.window.load_url(self.backend.url + "/")
                threading.Thread(target=self.backend.supervise, daemon=True, name="supervisor").start()
            else:
                self.backend.state = "failed"
                self.log.error("startup failed: %s", self.backend.error)
        finally:
            self.booting.release()

    def _restarted(self) -> None:
        self._set_notice_from_health(restarted=True)
        self.window.load_url(self.backend.url + "/")

    def on_loaded(self) -> None:
        # F11 = full screen, Esc leaves it (works on every page, including the interface itself)
        js = ("if(!window.__aresKeys){window.__aresKeys=1;document.addEventListener('keydown',function(e){"
              "if(e.key==='F11'){e.preventDefault();window.pywebview&&pywebview.api.toggle_fullscreen();}});}")
        if self.notice and self.backend and (self.window.get_current_url() or "").startswith(self.backend.url):
            msg, self.notice = self.notice, None
            js += ("(function(){var d=document.createElement('div');d.setAttribute('role','alert');d.style.cssText="
                   "'position:fixed;left:50%;top:14px;transform:translateX(-50%);z-index:99999;max-width:760px;"
                   "background:#1d1606;border:1px solid #f2c94c;color:#ffe9a8;border-radius:10px;padding:12px 40px 12px 16px;"
                   "font:13.5px/1.5 Segoe UI,system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.5)';"
                   "d.innerHTML='<b>Notice</b> &middot; " + msg.replace("'", "\\'") + "';var x=document.createElement('button');"
                   "x.textContent='\\u00d7';x.title='Dismiss';x.style.cssText='position:absolute;right:8px;top:6px;background:none;"
                   "border:none;color:#ffe9a8;font-size:20px;cursor:pointer';x.onclick=function(){d.remove()};d.appendChild(x);"
                   "document.body.appendChild(d);})();")
        try:
            self.window.evaluate_js(js)
        except Exception:  # noqa: BLE001
            pass

    def go(self, page: str) -> None:
        if self.backend and self.backend.state == "ready":
            self.window.evaluate_js(f"location.hash='/{page}'")

    def about(self) -> None:
        import webview
        html = (DESK_DIR / "about.html").read_text(encoding="utf-8")
        html = html.replace("{{VERSION}}", self.version).replace("{{DATA}}", str(DATA_DIR)).replace(
            "{{BUILD}}", "installed desktop build" if FROZEN else "source checkout")
        webview.create_window("About ARES", html=html, width=520, height=520, resizable=False, background_color="#040914")

    def menu(self):
        from webview.menu import Menu, MenuAction, MenuSeparator
        return [
            Menu("ARES", [MenuAction("Mission Overview", lambda: self.go("overview")),
                          MenuAction("3D Health Hologram", lambda: self.go("body")),
                          MenuAction("Emergency Command", lambda: self.go("emergency")),
                          MenuAction("Mission Simulation", lambda: self.go("sim")),
                          MenuSeparator(), MenuAction("Quit ARES", lambda: self.window.destroy())]),
            Menu("View", [MenuAction("Full screen (F11)", lambda: self.window.toggle_fullscreen()),
                          MenuAction("Reload interface", lambda: self.backend and self.window.load_url(self.backend.url + "/"))]),
            Menu("System", [MenuAction("System status", lambda: self.go("system")),
                            MenuAction("Open data folder", lambda: open_folder(DATA_DIR)),
                            MenuAction("Open logs folder", lambda: open_folder(LOG_DIR))]),
            Menu("Help", [MenuAction("About ARES", self.about)]),
        ]

    def run(self) -> int:
        import webview
        lock = InstanceLock(DATA_DIR / "ares.lock")
        if not lock.acquire():
            self.log.info("second launch refused: ARES is already running")
            webview.create_window("ARES is already running", html=(DESK_DIR / "already_running.html").read_text(encoding="utf-8"),
                                  width=460, height=240, resizable=False, background_color="#040914")
            webview.start()
            return 0
        self.log.info("ARES %s starting (data %s, %s)", self.version, DATA_DIR, "frozen" if FROZEN else "source")
        try:
            self.window = webview.create_window(
                APP_TITLE, url=(DESK_DIR / "splash.html").as_uri(), js_api=Api(self), width=1600, height=960,
                min_size=(1100, 700), confirm_close=True, background_color="#040914", text_select=True,
                menu=self.menu())
            self.window.events.loaded += self.on_loaded
            webview.settings["ALLOW_DOWNLOADS"] = True       # CSV / PDF test reports
            gui = "edgechromium" if sys.platform == "win32" else None
            webview.start(self.boot, gui=gui, private_mode=False, storage_path=str(DATA_DIR / "webview"),
                          # WinForms' System.Drawing.Icon() only accepts .ico files - a .png crashes the window thread
                          icon=str(DESK_DIR / "assets" / ("ares.ico" if sys.platform == "win32" else "ares.png")),
                          localization={"global.quitConfirmation": "Quit ARES? Monitoring stops; everything recorded is saved."})
        except Exception as ex:  # noqa: BLE001
            self.log.exception("window could not start")
            fatal(f"ARES could not open its window:\n{ex}\n\nOn Windows this needs the Microsoft Edge WebView2 Runtime "
                  f"(included with Windows 10/11). Logs: {LOG_DIR}")
            return 1
        finally:
            if self.backend:
                self.backend.stop()
            lock.release()
            self.log.info("ARES closed")
        return 0


def fatal(msg: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "ARES", 0x10)
    else:
        print(msg, file=sys.stderr)


# ------------------------------------------------------------------ headless self-test (CI / support)
def self_test() -> int:
    log = setup_log()
    report: dict = {"version": app_version(), "data_dir": str(DATA_DIR), "frozen": FROZEN}
    lock = InstanceLock(DATA_DIR / "ares.lock")
    report["single_instance_lock"] = lock.acquire()
    b = Backend(log)
    report["port"] = b.port
    t0 = time.time()
    b.start()
    ok = b.wait_ready()
    report["startup_s"] = round(time.time() - t0, 1)
    report["ready"] = ok
    report["checks"] = b.health.get("checks")
    if ok:
        for path in ("/", "/app/" + "", "/anatomy-assets/ares_body.glb", "/vendor/plotly.min.js", "/api/anomalies",
                     "/api/medical-guidance?astronaut=AST-1", "/api/simulation", "/api/history/sessions"):
            try:
                with urllib.request.urlopen(b.url + path, timeout=10) as r:
                    report[path] = r.status
            except Exception as ex:  # noqa: BLE001
                report[path] = str(ex)[:80]
        report.pop("/app/", None)
    b.stop()
    report["backend_exit_code"] = b.proc.returncode if b.proc else None
    report["error"] = b.error
    lock.release()
    print(json.dumps(report, indent=1))
    return 0 if ok and report["backend_exit_code"] == 0 else 1


def headless() -> int:
    """Backend + supervisor without a window (testing, kiosk/remote displays). Ctrl+C / SIGTERM stops it cleanly."""
    import signal
    log = setup_log()
    lock = InstanceLock(DATA_DIR / "ares.lock")
    if not lock.acquire():
        print(json.dumps({"event": "already_running", "data_dir": str(DATA_DIR)}), flush=True)
        return 3
    b = Backend(log)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):   # SIGBREAK = Ctrl+Break on Windows
        if sig is not None:
            signal.signal(sig, lambda *_: stop.set())
    b.on_restarted = lambda: print(json.dumps({"event": "restarted", "port": b.port, "restarts": len(b.restarts)}), flush=True)
    b.start()
    if not b.wait_ready():
        print(json.dumps({"event": "failed", "error": b.error}), flush=True)
        b.stop()
        lock.release()
        return 1
    print(json.dumps({"event": "ready", "port": b.port, "url": b.url, "backend_pid": b.proc.pid,
                      "previous_session_unclean": b.health.get("previous_session_unclean"),
                      "recovery": b.health.get("recovery")}), flush=True)
    threading.Thread(target=b.supervise, daemon=True).start()
    while not stop.wait(0.5):
        if b.state == "failed":
            print(json.dumps({"event": "failed", "error": b.error}), flush=True)
            break
    b.stop()
    lock.release()
    print(json.dumps({"event": "stopped", "backend_exit_code": b.proc.returncode}), flush=True)
    return 0


def main() -> int:
    if "--backend" in sys.argv:
        sys.path.insert(0, str(EXE_DIR))
        os.environ.setdefault("ARES_DATA_DIR", str(DATA_DIR))
        from ares.desktop_backend import main as backend_main
        return backend_main(sys.argv[1:])
    if "--self-test" in sys.argv:
        return self_test()
    if "--headless" in sys.argv:
        return headless()
    return DesktopApp().run()


if __name__ == "__main__":
    if FROZEN:
        import multiprocessing
        multiprocessing.freeze_support()
    sys.exit(main())
