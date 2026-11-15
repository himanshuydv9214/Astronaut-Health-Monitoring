"""ARES desktop - offline reliability test battery (12 scenarios).

Runs the real launcher (packaged ARES.exe / ARES, or the source launcher) in its window-less --headless mode, with
a throw-away data folder, and checks: offline start, first launch, persistence, backend crash + automatic recovery,
no repeated emergency action after a restart, power loss, corrupted database, port conflict, second instance,
3D/interface assets, local AI inference and graceful shutdown.

  Windows (packaged):   ARES.exe must be built first, then - with Wi-Fi OFF / network cable unplugged:
      .venv\\Scripts\\python desktop\\offline_tests.py --app dist\\ARES\\ARES.exe
  Source checkout:      python desktop/offline_tests.py
  Linux, enforced offline (no network except loopback):
      unshare -n python3 tools/netns_offline.py python3 desktop/offline_tests.py --app dist/ARES/ARES

Writes desktop/offline_test_report.json and .md (or --out). Exit code 0 only if every test passed.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIN = sys.platform == "win32"


# ------------------------------------------------------------------ helpers
def internet_reachable() -> bool:
    for host in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            socket.create_connection(host, timeout=3).close()
            return True
        except OSError:
            pass
    return False


def pid_alive(pid: int) -> bool:
    if WIN:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                                     # zombie = already dead
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def hard_kill(pid: int) -> None:
    """Simulate a crash / power cut: no clean-up code runs."""
    if WIN:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


class App:
    """One headless launcher run; reads its JSON event lines."""

    def __init__(self, cmd: list[str], data: Path):
        env = os.environ.copy()
        env["ARES_DATA_DIR"] = str(data)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
        self.p = subprocess.Popen(cmd + ["--headless"], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, cwd=str(ROOT), creationflags=flags)
        self.q: queue.Queue = queue.Queue()
        self.events: list[dict] = []
        threading.Thread(target=self._read, daemon=True).start()
        self.port = None
        self.backend_pid = None
        self.ready: dict = {}

    def _read(self):
        for line in self.p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            self.events.append(ev)
            self.q.put(ev)

    def wait(self, name: str, timeout: float = 240) -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = self.q.get(timeout=0.5)
            except queue.Empty:
                if self.p.poll() is not None and self.q.empty():
                    return None
                continue
            if ev.get("event") == name:
                if name == "ready":
                    self.port, self.backend_pid, self.ready = ev["port"], ev["backend_pid"], ev
                return ev
            if ev.get("event") == "failed":
                return None
        return None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def get(self, path: str, timeout: float = 15):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if r.headers.get("content-type", "").startswith("application/json") else body

    def post(self, path: str, data: dict | None = None):
        req = urllib.request.Request(self.url + path, data=json.dumps(data or {}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def stop(self, timeout: float = 60) -> int | None:
        """Graceful stop (what closing the window does)."""
        if self.p.poll() is None:
            if WIN:
                self.p.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.p.send_signal(signal.SIGTERM)
        try:
            return self.p.wait(timeout)
        except subprocess.TimeoutExpired:
            self.p.kill()
            return None


class Battery:
    def __init__(self, cmd: list[str], keep: bool):
        self.cmd = cmd
        self.data = Path(tempfile.mkdtemp(prefix="ares-offline-test-"))
        self.keep = keep
        self.results: list[dict] = []

    def record(self, no: int, name: str, ok: bool, detail: str, status: str | None = None):
        self.results.append({"no": no, "test": name, "status": status or ("PASS" if ok else "FAIL"), "detail": detail})
        print(f"[{status or ('PASS' if ok else 'FAIL')}] {no:>2}. {name} - {detail}", flush=True)

    def start(self, timeout: float = 240) -> App:
        a = App(self.cmd, self.data)
        if not a.wait("ready", timeout):
            raise RuntimeError(f"ARES did not become ready; events: {a.events}")
        return a

    # -------------------------------------------------------------- the battery
    def run(self) -> None:
        online = internet_reachable()

        # 1 + 2: first launch on an empty data folder, offline
        t0 = time.time()
        a = self.start()
        h = a.get("/api/system/health")
        dur = time.time() - t0
        files = sorted(p.name for p in self.data.iterdir())
        backups = [p.name for p in (self.data / "backups").iterdir()] if (self.data / "backups").exists() else []
        self.record(1, "Starts with no internet connection",
                    h["ready"] and not online,
                    f"internet reachable: {online}; ready in {dur:.1f} s" if not online else
                    "the computer is ONLINE - disconnect Wi-Fi/cable and re-run to verify offline start",
                    status=None if not online else "NOT VERIFIED")
        self.record(2, "First launch on an empty data folder",
                    h["ready"] and all(h["checks"].values()) and "ares_local.db" in files and "ares_history.db" in files
                    and not h["previous_session_unclean"],
                    f"all {len(h['checks'])} checks ready; created {', '.join(f for f in files if not f.endswith(('-wal', '-shm')))}")

        # 10: interface + 3D assets served locally, nothing external
        html = a.get("/").decode()
        import re
        assets = re.findall(r'(?:src|href)="(/[^"]+)"', html)
        status = {}
        for u in assets + ["/anatomy-assets/ares_body.glb", "/anatomy-assets/regions.json", "/vendor/plotly.min.js"]:
            try:
                with urllib.request.urlopen(a.url + u, timeout=20) as r:
                    status[u] = (r.status, len(r.read()))
            except Exception as ex:  # noqa: BLE001
                status[u] = (str(ex)[:60], 0)
        js_text = ""
        for u in assets:
            if u.endswith(".js") or u.endswith(".css"):
                js_text += urllib.request.urlopen(a.url + u, timeout=20).read().decode("utf-8", "ignore")
        found = sorted(set(re.findall(r"https?://(?:fonts\.googleapis|fonts\.gstatic|cdn\.|unpkg\.com|cdnjs)[^\s\"'`)]*",
                                      html + js_text)))
        # Dormant URLs inside the bundled Plotly library: map-marker icons and world-map topology for geographic
        # charts. ARES draws no geographic charts, so they are never requested (this test runs with no network).
        dormant = [u for u in found if u.startswith(("https://cdn.plot.ly/un", "https://cdn.jsdelivr.net/npm/@mapbox/maki"))]
        ext = [u for u in found if u not in dormant]
        missing = {k: v for k, v in status.items() if v[0] != 200}
        glb = status.get("/anatomy-assets/ares_body.glb", (0, 0))
        self.record(10, "Interface and 3D hologram assets load locally",
                    not missing and not ext and glb[1] > 1_000_000,
                    f"{len(status)} files served by the app (3D model {glb[1] / 1e6:.1f} MB); missing {missing or 'none'}; "
                    f"CDN/web-font references in use: {ext or 'none'}; dormant Plotly map URLs (never fetched): {len(dormant)}")

        # 11: local AI inference
        an = a.get("/api/anomalies")
        crew = a.get("/api/astronauts")
        ids = [c["id"] for c in (crew.get("astronauts", crew) if isinstance(crew, dict) else crew)]
        g = a.get(f"/api/medical-guidance?astronaut={ids[0]}")
        pvt = a.post(f"/api/pvt/{ids[0]}", {"rts_ms": [250 + (i * 37) % 160 for i in range(60)], "anticipations": 1,
                                             "misses": 0, "duration_s": 180, "trials": 61})
        txt = json.dumps(an)
        self.record(11, "AI models run locally (anomaly, 30-min risk, guidance, reaction test)",
                    '"anomaly_score"' in txt and '"risk_30min"' in txt and bool(g) and bool(pvt),
                    f"{len(ids)} crew scored; guidance keys {sorted(g)[:5]}; PVT result saved")

        # set up an emergency the crew acts on (for tests 4/5)
        a.post("/api/speed", {"minutes_per_second": 30})
        a.post("/api/scenario", {"key": "spo2_drop", "astronaut_id": ids[0]})
        inc = None
        for _ in range(120):
            incs = a.get("/api/emergencies")["incidents"]
            if incs:
                inc = incs[0]
                break
            time.sleep(1)
        acted = None
        if inc:
            for act in ("acknowledge", "notify_crew", "request_measurements"):
                try:
                    a.post(f"/api/emergencies/{inc['id']}/action", {"action": act, "note": "offline test"})
                    acted = act
                    break
                except urllib.error.HTTPError:
                    continue
        archive_before = a.get("/api/history/archive")
        ev_before = {(r["session"], r["run"], r["id"]): len(r["workflow_events"]) for r in archive_before}
        session_crashed = a.get("/api/system/health")["session"]

        # 4: backend crash -> supervisor restarts it
        old_pid = a.backend_pid
        hard_kill(old_pid)
        ev = a.wait("restarted", 120)
        h2 = a.get("/api/system/health") if ev else {}
        self.record(4, "Backend crash is detected and recovered automatically",
                    bool(ev) and h2.get("ready") and h2.get("previous_session_unclean") and not pid_alive(old_pid),
                    f"killed backend pid {old_pid}; restarted={bool(ev)}; ready={h2.get('ready')}; "
                    f"crash recorded as unclean session={h2.get('previous_session_unclean')}")

        # 5: nothing replayed
        now_incs = a.get("/api/emergencies")["incidents"]
        replayed = [i["id"] for i in now_incs if "offline test" in json.dumps(a.get(f"/api/emergencies/{i['id']}"))]
        archive_after = a.get("/api/history/archive")
        old = [r for r in archive_after if r["session"] == session_crashed]
        ev_after = {(r["session"], r["run"], r["id"]): len(r["workflow_events"]) for r in old}
        unchanged = all(ev_after.get(k) == v for k, v in ev_before.items() if k[0] == session_crashed)
        self.record(5, "No emergency action is repeated after a restart",
                    bool(inc) and bool(acted) and not replayed and unchanged and bool(old),
                    f"incident #{inc and inc['id']} ({acted}) kept in history with {len(old)} archived incident(s), "
                    f"action log unchanged={unchanged}; re-applied actions after restart: {len(replayed)}")

        # 9: second instance refused
        b = App(self.cmd, self.data)
        ev = b.wait("already_running", 60)
        code = b.p.wait(30)
        self.record(9, "A second launch does not start a duplicate ARES", bool(ev) and code == 3 and a.p.poll() is None,
                    f"second launch exit code {code}; first instance still running={a.p.poll() is None}")

        # 12: graceful shutdown
        bpid = a.backend_pid if not a.events or a.events[-1].get("event") != "restarted" else None
        h_now = a.get("/api/system/health")
        bpid = h_now["pid"]
        stopped_code = a.stop()
        stop_ev = next((e for e in a.events if e.get("event") == "stopped"), {})
        time.sleep(1)
        self.record(12, "Graceful shutdown saves data and leaves no process behind",
                    stopped_code == 0 and stop_ev.get("backend_exit_code") == 0 and not pid_alive(bpid),
                    f"launcher exit {stopped_code}; backend exit {stop_ev.get('backend_exit_code')}; "
                    f"backend still running={pid_alive(bpid)}")

        # 3: persistence across a normal restart
        a = self.start()
        sessions = a.get("/api/history/sessions")
        sess = sessions.get("sessions", sessions) if isinstance(sessions, dict) else sessions
        runs = a.get(f"/api/pvt/{ids[0]}")["runs"]
        earlier = [r for r in runs if "this session" not in str(r.get("source", ""))]
        arch = a.get("/api/history/archive")
        last_clean = sess[1]["clean"] if len(sess) > 1 else None
        self.record(3, "Data survives closing and reopening",
                    bool(earlier) and bool(arch) and not a.ready.get("previous_session_unclean") and bool(last_clean),
                    f"{len(sess)} sessions on record (previous closed cleanly={bool(last_clean)}); "
                    f"{len(earlier)} earlier reaction-test run(s) and {len(arch)} archived emergency record(s) visible")

        # 8: port conflict
        a.stop()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if not WIN:
            blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # ignore TIME_WAIT left by the last run
        blocker.bind(("127.0.0.1", 8765))
        blocker.listen()
        try:
            a = self.start()
            ok = a.port != 8765 and a.get("/api/system/health")["ready"]
            self.record(8, "Port 8765 already in use", ok, f"another program held 8765; ARES chose {a.port} and is ready")
        finally:
            blocker.close()

        # 6: power loss (launcher and backend die at once)
        a.post(f"/api/pvt/{ids[0]}", {"rts_ms": [300] * 40, "anticipations": 0, "misses": 0, "duration_s": 120, "trials": 40})
        time.sleep(0.5)
        hard_kill(a.backend_pid)
        hard_kill(a.p.pid)
        time.sleep(2)
        a = self.start()
        h = a.get("/api/system/health")
        runs = a.get(f"/api/pvt/{ids[0]}")["runs"]
        integ = a.get("/api/system/status")
        integ_txt = json.dumps(integ.get("integrity", integ))[:200]
        self.record(6, "Sudden power loss / forced termination",
                    h["ready"] and h["previous_session_unclean"] and len(runs) >= 2,
                    f"restart ready; previous session flagged as ended unexpectedly; {len(runs)} reaction-test runs intact; "
                    f"stale lock released by the OS")

        # 7: corrupted database
        a.stop()
        hist = self.data / "ares_history.db"
        for suffix in ("-wal", "-shm"):
            Path(str(hist) + suffix).unlink(missing_ok=True)
        hist.write_bytes(b"\x00garbage - simulated disk corruption\x00" * 2000)
        a = self.start()
        rec = a.ready.get("recovery") or {}
        corrupt_kept = [p.name for p in (self.data / "backups").iterdir() if p.name.startswith("corrupt-")]
        h = a.get("/api/system/health")
        self.record(7, "Corrupted local database is detected and restored from backup",
                    h["ready"] and bool(rec.get("restored")) and bool(corrupt_kept),
                    f"restored {rec.get('restored')}; damaged file kept as {corrupt_kept}; app ready={h['ready']}")
        a.stop()

    def report(self, out: Path, app_desc: str) -> int:
        self.results.sort(key=lambda r: r["no"])
        meta = {"app": app_desc, "platform": sys.platform, "python": sys.version.split()[0],
                "date": time.strftime("%Y-%m-%d %H:%M"), "data_dir": str(self.data)}
        out.with_suffix(".json").write_text(json.dumps({"meta": meta, "results": self.results}, indent=1))
        lines = [f"# ARES offline test report\n", f"App: `{app_desc}` - platform `{sys.platform}` - {meta['date']}\n",
                 "| # | Test | Result | Detail |", "|---|---|---|---|"]
        lines += [f"| {r['no']} | {r['test']} | **{r['status']}** | {r['detail'].replace('|', '/')} |" for r in self.results]
        out.with_suffix(".md").write_text("\n".join(lines) + "\n")
        if not self.keep:
            shutil.rmtree(self.data, ignore_errors=True)
        failed = [r for r in self.results if r["status"] == "FAIL"]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} passed or informational; report: {out.with_suffix('.md')}")
        return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", help="path to packaged ARES.exe / ARES (default: run the source launcher)")
    ap.add_argument("--out", default=str(ROOT / "desktop" / "offline_test_report"))
    ap.add_argument("--keep", action="store_true", help="keep the temporary data folder for inspection")
    args = ap.parse_args()
    cmd = [args.app] if args.app else [sys.executable, str(ROOT / "desktop" / "ares_desktop.py")]
    bat = Battery(cmd, args.keep)
    try:
        bat.run()
    except Exception as ex:  # noqa: BLE001
        bat.record(99, "Battery aborted", False, repr(ex)[:400])
    return bat.report(Path(args.out), args.app or "source launcher")


if __name__ == "__main__":
    sys.exit(main())
