# ARES technical audit and upgrade plan (Nov 15, 2026)

## Architecture found

- **Backend:** Python FastAPI + Uvicorn. One in-process `AresEngine` runs on a background clock thread (mission minutes per real second) behind a lock. Local SQLite hash-chained store. Models: Isolation Forest + gradient-boosted forecaster (joblib), all local.
- **Frontends (two, inconsistent):**
    - the vanilla JS dashboard at `/` (6 tabs, Plotly served locally, polling `/api/state` every 1 s);
    - the React + Three.js 3D twin at `/twin` (WebSocket `/ws/anatomy` with polling fallback).
- **Communication:** REST JSON + one WebSocket. No cloud calls in normal operation; NASA DONKI refresh is optional and cached.

## Audit table

| Existing feature | Current implementation | Problems identified | Improvement made | Files |
|---|---|---|---|---|
| Navigation / layout | Two separate apps with different styles | Inconsistent look; 3D body hidden behind a link; heavy jargon | One React app at `/` with a single navy/cyan design system and plain-language labels; old dashboard kept at `/classic` | `web3d/src/*`, `ares/api/server.py` |
| 3D body | BodyParts3D GLB, solid colours | Not holographic; no vascular layer; organ panel lacked actions and long-term info | Holographic shader (fresnel rim, scanlines, additive glow), new arteries/veins layer, transparent / organs / vessels / skeleton modes, four-part guidance panel | `assets/anatomy/*`, `web3d/src/components/Hologram*.tsx` |
| Health guidance | Protocol steps only, inside the emergency report | No "what is happening", no long-term effects or care | Four sections from live data + local knowledge base, with evidence labels and sources | `ares/emergency/guidance.py`, `knowledge_base/health_guidance.json` |
| Longitudinal table | Daily rows × raw parameter codes | Mis-aligned, unexplained, only 2–3 days | "Health changes over time": baseline / current / change / trend sparkline / updated / status, row → history chart | `ares/twin/drift.py`, `web3d/src/pages/Crew.tsx` |
| Drift detection | `drift_from_premission` (posterior mean vs frozen prior) | Always ~0 (baseline adapts to itself) → drift never shown | Hourly resting means vs own reference period; z, direction, duration, sudden vs gradual, data quality | `ares/twin/drift.py`, `ares/twin/twin.py` |
| Info on tables | Short hints | No explanation of columns, units, origin | Information button on every table with specific text | `web3d/src/info.ts` |
| Emergency command | Incident list + report + acknowledge | Only one real action; no workflow, timeline or report export | 10-step workflow with real actions, event timeline, Markdown report download, escalation floor, Earth sync status | `ares/emergency/workflow.py`, `server.py` |
| PVT | Start buttons only; scoring server-side | No stop/pause/terminate, no per-trial ms list, no history, no report | State machine (ready / countdown / running / paused / completed / terminated), `performance.now` + event timestamps, full stats, histogram, history, download | `web3d/src/pages/Alertness.tsx`, `ares/behavioral/pvt.py` |
| Mission simulation | Scenario cards inject into the running clock | No start/pause/stop/reset, no script, no visible progression | Controller with 8 scripted scenarios that drive the real engine, progress, event feed, reset rebuilds a fresh engine | `ares/simulation/mission_sim.py` |
| Sync queue | Priority store-and-forward | Duplicates possible; no waiting reason or stats | De-duplication, waiting reason (blackout / bandwidth), sync stats | `ares/mission/comms.py` |
| API | `/api/state` mega-payload + a few actions | No grouped endpoints | `/api/astronauts`, `/health`, `/health/history`, `/drift`, `/anomalies`, `/emergencies`, `/pvt`, `/mission`, `/simulation`, `/medical-guidance`, `/system/status`; optional `ARES_TOKEN` local auth | `server.py` |
| Offline | Local Plotly, local GLB | Not verified with the network actually blocked | Browser test with every non-local request blocked | `tests/test_offline_ui.py` |

## Things that cannot be done with the available assets

- **Arm and leg blood vessels:** BodyParts3D release 3.0 only models vessels of the neck, trunk and lungs. The hologram shows those real vessels and does not invent limb vessels.
- **Approved medical protocols:** real flight procedures are controlled documents. The knowledge base stays labelled DEMO / not approved.
- **Local language model:** not included. The assistant is retrieval-only and the emergency system needs no LLM.
