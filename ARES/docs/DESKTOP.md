# ARES Desktop — standalone offline application

ARES now runs as a normal desktop program. Double-click the icon and it starts its own background service, checks
its data, loads the AI models, the knowledge base and the 3D anatomy, then opens the mission-control window.
There is no terminal, browser or internet connection involved, and the target PC needs neither Python nor Node.js.

> Research prototype. ARES is not a medical device, is not clinically validated and is **not flight-certified**.
> The packaging work here makes it robust on an ordinary PC; it is not a spacecraft software qualification.

---

## 1. Audit summary (what existed, what changed)

| Area | Before | Now |
|---|---|---|
| Start | `START_ARES.bat` / `run_ares.py` → console window + browser tab | Double-click **ARES** → native window. No console. The old launchers still work. |
| Backend | FastAPI/uvicorn on 127.0.0.1:8765, started by hand | Started and supervised by the app; port chosen automatically; loopback only |
| Data location | `data/` inside the project | Installed app: `%LOCALAPPDATA%\ARES\data`. Portable: `data\` next to `ARES.exe`. Source checkout: `data/` (unchanged) |
| Persistence | Hash-chained audit log (`ares_local.db`) | + `ares_history.db` (sessions, emergencies with crew actions, reaction-test runs, simulation runs), SQLite WAL, integrity check and backup at every start, automatic restore |
| Shutdown | Ctrl+C | Exit confirmation → final save → clean session mark → databases closed → no process left |
| Crash handling | none | Backend restarted automatically (max. 3 times in 10 min), previous session marked "ended unexpectedly", notice shown to the crew |
| Offline | Already offline-capable (local Plotly, local fonts, local GLB) | Verified by a 12-scenario test with the network physically disabled |

Nothing was rebuilt from scratch, and no working service was replaced with a dummy. The team's restyled interface
(`web3d/src`, `ares/web3d_dist`) was not touched. The desktop app packages whatever interface is built in
`ares/web3d_dist`.

**Files added:** `ares/paths.py`, `ares/persistence.py`, `ares/startup_status.py`, `ares/desktop_backend.py`,
`desktop/` (launcher, startup screen, icon, PyInstaller spec, installer script, build scripts, offline tests),
`tests/test_desktop.py`, `tools/netns_offline.py`, `desktop/ci/build-desktop.yml` (GitHub Actions workflow — move it to `.github/workflows/`), this document.
**Files changed:** `ares/api/server.py` (startup stages, health/version/shutdown/history endpoints, periodic + on-action
saving), `ares/storage.py` (data folder, WAL, close), `ares/radiation/donki.py` (cache location),
`ares/simulation/mission_sim.py` (save before reset), `ares/__init__.py` (version 0.4.0), test fixtures.

## 2. Framework choice: pywebview + PyInstaller + Inno Setup

| Option | Verdict |
|---|---|
| **Electron** | Ships its own Chromium (~150 MB) **plus** we would still have to bundle Python for the backend as a sidecar. That means two runtimes, a Node toolchain and two processes to keep in sync. Rejected. |
| **Tauri** | Small, but still needs the Python sidecar, plus a Rust toolchain for every team member who builds. Rejected for a 5-person hackathon team. |
| **pywebview** (chosen) | A native window around the OS web engine (Edge **WebView2** on Windows, Qt WebEngine/WebKitGTK on Linux). It is written in Python, so the launcher, the backend and the packaging all stay in one language and one runtime. It reuses the existing built React interface unchanged. |
| **PyInstaller** (one-folder) | Freezes Python + every library + models + data into `dist\ARES\`. One `ARES.exe` serves as both the window process and (`--backend`) the service process. |
| **Inno Setup** | Free, standard Windows installer: per-user install (no admin), Start-menu + desktop shortcuts, uninstaller, works offline. |

WebView2 is built into Windows 11 and updated Windows 10. Setup checks for it. For PCs without it, you can bundle
Microsoft's *offline* WebView2 installer (see §4).

## 3. How it works

```
ARES.exe (window process)                         ARES.exe --backend (hidden service process)
 ├─ single-instance lock (data\ares.lock)          ├─ integrity check + backup + restore if corrupt
 ├─ picks port 8765, or a free one if taken        ├─ opens ares_history.db / ares_local.db (WAL)
 ├─ starts the service (no console window)  ──▶    ├─ loads AI models, knowledge base, 3D anatomy
 ├─ startup screen shows each stage live    ◀──    ├─ writes startup_status.json at each stage
 ├─ /api/system/health ready → opens interface     ├─ serves the interface on 127.0.0.1 only
 ├─ supervisor: restarts the service on crash      ├─ saves every 30 s and right after each crew action
 └─ Exit → confirm → POST /api/system/shutdown ──▶ └─ final save, clean-session mark, exits; also exits by
                                                      itself if the window process disappears (watchdog)
```

**Safety rule:** a restart never repeats a medical intervention or emergency action. On restart the service begins
a new session with live monitoring. Emergencies from the previous session, with every crew action taken, are kept
read-only in the history (**Data & System → history**, `/api/history/archive`). The audit log is append-only and is
never replayed. After a crash or power loss the window shows a notice asking the crew to review open emergencies
before acting. This is verified by offline test 5.

**Menu:** ARES (Mission Overview, 3D Hologram, Emergency Command, Simulation, Quit) · View (Full screen F11, Reload) ·
System (System status, Open data folder, Open logs folder) · Help (About: version, build, data folder, disclaimer).

**Downloads:** CSV/PDF test reports are saved through the window's normal download prompt (enabled in the launcher).

**Logs:** `data\logs\desktop.log` (window/supervisor), `data\logs\backend.log` (service), rotated automatically.

## 4. Building it (once, on a Windows 10/11 PC)

1. Make sure the interface is built (`ares\web3d_dist\index.html` exists). If not: `cd web3d && npm ci && npm run build`.
2. Optional, for the installer: install **Inno Setup 6** (`winget install JRSoftware.InnoSetup`).
3. Optional, for PCs without WebView2: download Microsoft's *Evergreen Standalone x64* WebView2 installer and save it as
   `desktop\redist\MicrosoftEdgeWebView2RuntimeInstallerX64.exe`. Setup will then install it silently with no internet.
4. Double-click **`desktop\build_windows.bat`**. It creates or uses `.venv`, installs PyInstaller + pywebview, builds,
   **self-tests the built app**, then makes:
   - `dist\ARES\ARES.exe` — the app
   - `dist\ARES-0.4.0-portable-win64.zip` — portable version
   - `dist\installer\ARES-Setup-0.4.0.exe` — the installer

**No Windows PC handy, or the build is blocked?** Move `desktop/ci/build-desktop.yml` to `.github/workflows/build-desktop.yml`, push to GitHub, then go to the **Actions** tab → *Build ARES desktop* →
**Run workflow**. It builds the Windows installer, portable zip and Linux tarball on GitHub's machines, runs the 12
reliability tests there, and offers the files under the run's **Artifacts**.

**Without building at all (for development):** `powershell -ExecutionPolicy Bypass -File desktop\create_shortcut.ps1`
puts an ARES shortcut on the desktop. It opens the same window straight from the project's `.venv`, with no console.

Linux: `bash desktop/build_linux.sh` → `dist/ARES/ARES` and `dist/ARES-0.4.0-linux-x64.tar.gz`.

## 5. Installing and running (end users)

**Installer:** run `ARES-Setup-0.4.0.exe` → Next → (desktop shortcut) → Install → *Start ARES now*.
No admin rights or internet are needed. It installs to `%LOCALAPPDATA%\Programs\ARES` and keeps data in
`%LOCALAPPDATA%\ARES\data`. Uninstall via *Settings → Apps* or the Start-menu entry. The uninstaller asks whether
to also delete the health data, and defaults to **keeping** it.

**Portable:** unzip `ARES-0.4.0-portable-win64.zip` anywhere (USB stick included) and run `ARES\ARES.exe`. Data stays in
`ARES\data` next to it.

**First start** takes about 15–30 s (models and the 3D model load; a backup is made). Later starts are faster.
Minimum: Windows 10 1809+ x64, 4 GB RAM, a GPU with WebGL (any normal laptop) for the 3D hologram, ~400 MB disk.

## 6. Offline test report

The test battery is `desktop/offline_tests.py`. It drives the real packaged app in its window-less `--headless`
mode with a throw-away data folder. On Linux it was run inside a network namespace with **no network except
loopback** (`tools/netns_offline.py`), so "offline" was enforced by the OS rather than assumed.

| # | Scenario | Linux build (verified here) | Windows build |
|---|---|---|---|
| 1 | Starts with no internet | **PASS** – ready in 13.8 s, internet unreachable | run on Windows ¹ |
| 2 | First launch, empty data folder | **PASS** – all 7 components ready, databases created | ¹ |
| 3 | Data survives close + reopen | **PASS** – sessions, reaction-test runs, emergency archive visible | ¹ |
| 4 | Backend crash → automatic recovery | **PASS** – service killed, restarted, crash recorded | ¹ |
| 5 | No emergency action repeated after restart | **PASS** – 0 re-applied actions, archive unchanged | ¹ |
| 6 | Power loss (both processes killed) | **PASS** – flagged as unexpected end, data intact, lock freed | ¹ |
| 7 | Corrupted database | **PASS** – detected, damaged copy kept, restored from backup | ¹ |
| 8 | Port 8765 already in use | **PASS** – chose another port, ready | ¹ |
| 9 | Second launch | **PASS** – refused (exit 3), first instance unaffected | ¹ |
| 10 | Interface + 3D assets local | **PASS** – all files served locally, 3D model 6.6 MB, no CDN/web fonts in use ² | ¹ |
| 11 | Local AI inference | **PASS** – anomaly + 30-min risk for 4 crew, guidance, reaction test | ¹ |
| 12 | Graceful shutdown | **PASS** – exit 0, no process left behind | ¹ |

Full output: `desktop/offline_test_report_linux.md`. Also verified here: the full unit/integration test suite
(50 tests, 0 failures, 1 existing scenario-dependent skip), the frozen app's `--self-test` in an empty environment
with no Python on PATH, `build_linux.sh` end-to-end, and the desktop window itself (startup screen with live stages,
then the full interface with the 3D hologram, rendered with Qt WebEngine).

¹ **Not yet run on Windows.** This work was done in a Linux environment that cannot build or run a Windows `.exe`, so
`ARES.exe` and `ARES-Setup-0.4.0.exe` have **not been compiled or tested yet**. The installer script has not been
compiled either. The code paths are cross-platform and the Windows-specific parts are written for Windows (WebView2
backend, `CREATE_NO_WINDOW`, `msvcrt` lock, process checks, Ctrl+Break stop, Inno Setup), but they are unverified
until run. After building, turn Wi-Fi off and run:
`.venv\Scripts\python desktop\offline_tests.py --app dist\ARES\ARES.exe` → `desktop\offline_test_report.md`.
The GitHub Actions workflow runs the same battery on Windows automatically (test 1 shows *NOT VERIFIED* there because
GitHub's machines are online).

² The bundled Plotly library contains two URLs (map icons, world-map shapes) used only by geographic charts. ARES
draws none, so they are never requested. The test reports them as dormant.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **"Windows protected your PC"** or **Smart App Control blocked ARES** | The build is not code-signed. SmartScreen: *More info → Run anyway*. Smart App Control (Windows 11) cannot be bypassed per app: use the source shortcut (`desktop\create_shortcut.ps1`, which runs the signed Python), sign the exe, or turn Smart App Control off (*Windows Security → App & browser control*). Antivirus may also quarantine fresh PyInstaller builds. Restore it / add an exclusion for the ARES folder. |
| Window opens but stays blank or white | WebView2 missing or broken. Install *Microsoft Edge WebView2 Runtime* (Evergreen Standalone, works offline). |
| Startup screen shows a red component | Its message says which part failed. Click **Open logs** (`backend.log`). *Models* → the `models` folder is missing from the build; *Interface* → `ares\web3d_dist` was not built before packaging. |
| Interface works but the 3D hologram is empty | WebGL is unavailable (remote desktop, some VMs, very old GPU drivers). Update the graphics driver, or use the PC directly. |
| "ARES is already running" | Another ARES window is open (check the taskbar). If ARES really is closed, the lock clears itself. A stale lock cannot block a start because the OS releases it when the process ends. |
| Port already in use | Handled automatically. ARES picks a free port. Nothing to do. |
| Notice "ARES was not closed normally last time" | Shown after a crash or power cut. The data was checked (and restored from backup if damaged). Review open emergencies in the history before acting. Nothing was repeated automatically. |
| Starting from source shows a console | Use the desktop shortcut (`pythonw`) or the built exe, not `python ...`. |
| Need to send logs to the team | *System → Open logs folder*, then zip `desktop.log` and `backend.log`. |
| Reset everything | Close ARES and delete `%LOCALAPPDATA%\ARES\data`. Earlier backups are in `data\backups` (5 kept). |

## 8. Spacecraft-oriented considerations (design notes, not a certification)

What the prototype already does in the right direction:
- No network dependency; listens on loopback only; no telemetry.
- Crash-only design: every write is committed SQLite (WAL); state is reloadable after a power cut.
- Integrity check and backup at every start, with automatic restore; the hash-chained audit log can be verified
  (*System status → integrity*).
- A supervised service with bounded restarts.
- No automatic repetition of interventions after a restart; the crew is told what happened.
- Deterministic local models with no online learning in flight.

What real flight use would additionally need (not done, and out of scope for this hackathon prototype):
- Requirements traceability, hazard analysis and software classification under NASA NPR 7150.2 / NASA-STD-8739.8.
- Medical-device-grade validation (clinical data, IEC 62304-style lifecycle).
- A real-time or partitioned OS, or at least a hardened and minimal host.
- Radiation-tolerant hardware with ECC memory and redundant storage.
- Signed builds and verified updates, plus formal configuration management.
- Fault injection campaigns and independent verification and validation (IV&V).
- Human-factors testing with crews.
- Integration with real vehicle sensor buses instead of simulated telemetry.

## 9. Command reference

```
ARES.exe                 normal start (window)
ARES.exe --self-test     start hidden, check every component, shut down, print a JSON report (exit 0 = OK)
ARES.exe --headless      service + supervisor without a window (tests, remote displays); Ctrl+C stops it cleanly
ARES_DATA_DIR=<folder>   environment variable: use a different data folder
portable.flag            file next to ARES.exe: keep data in .\data (portable mode)
```
