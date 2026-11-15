# ARES offline test report

App: `/tmp/ares_dist/ARES/ARES` - platform `linux` - 2026-11-15 06:22

| # | Test | Result | Detail |
|---|---|---|---|
| 1 | Starts with no internet connection | **PASS** | internet reachable: False; ready in 13.5 s |
| 2 | First launch on an empty data folder | **PASS** | all 8 checks ready; created ares.lock, ares_history.db, ares_local.db, backups, cache, logs, startup_status.json |
| 3 | Data survives closing and reopening | **PASS** | 3 sessions on record (previous closed cleanly=True); 1 earlier reaction-test run(s) and 1 archived emergency record(s) visible |
| 4 | Backend crash is detected and recovered automatically | **PASS** | killed backend pid 8297; restarted=True; ready=True; crash recorded as unclean session=True |
| 5 | No emergency action is repeated after a restart | **PASS** | incident #1 (acknowledge) kept in history with 1 archived incident(s), action log unchanged=True; re-applied actions after restart: 0 |
| 6 | Sudden power loss / forced termination | **PASS** | restart ready; previous session flagged as ended unexpectedly; 2 reaction-test runs intact; stale lock released by the OS |
| 7 | Corrupted local database is detected and restored from backup | **PASS** | restored [{'file': 'ares_history.db', 'from': '20261115-062220', 'corrupt_copy': 'corrupt-20261115-062238-ares_history.db'}]; damaged file kept as ['corrupt-20261115-062238-ares_history.db']; app ready=True |
| 8 | Port 8765 already in use | **PASS** | another program held 8765; ARES chose 34687 and is ready |
| 9 | A second launch does not start a duplicate ARES | **PASS** | second launch exit code 3; first instance still running=True |
| 10 | Interface and 3D hologram assets load locally | **PASS** | 5 files served by the app (3D model 6.6 MB); missing none; CDN/web-font references in use: none; dormant Plotly map URLs (never fetched): 2 |
| 11 | AI models run locally (anomaly, 30-min risk, guidance, reaction test) | **PASS** | 4 crew scored; guidance keys ['concern', 'note']; PVT result saved |
| 12 | Graceful shutdown saves data and leaves no process behind | **PASS** | launcher exit 0; backend exit 0; backend still running=False |
