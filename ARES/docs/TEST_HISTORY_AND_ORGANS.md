# ARES v0.5 — Permanent test history and interactive organ dossiers

Two additions, both running fully offline on the local backend:

1. **Every test is saved permanently.** This covers reaction tests (PVT-B), wellness check-ins, symptom reports and blood-test entries. Records survive closing and restarting ARES, a reboot, a crash or a power cut.
2. **Click any organ on the 3D hologram** to see its actual health events. Each event comes with its measurements against the astronaut's own baseline, the evidence, the onboard response procedures, possible long-term effects, long-term management and history. Organs without data say so.

> Research prototype. Not a medical device, not clinically validated, not flight-certified. Crew physiology in the demo is simulated; tests performed in the app are real inputs.

---

## 1. Audit (before the change)

| Area | Found |
|---|---|
| Database | SQLite: `ares_local.db` (hash-chained audit log) + `ares_history.db` (sessions, emergencies, simulation runs, `pvt_runs`) |
| Tests in the app | PVT-B reaction test (React + classic dashboard), daily wellness check-in (Samn-Perelli fatigue, mood, stress, workload, sleep quality), symptom report, lab entry (classic dashboard) |
| Persistence gaps | Only PVT summaries were saved, as one JSON blob with no trials or status. Stopped tests were not marked as stopped, and terminated tests were not saved at all. Check-ins, symptoms and labs lived in memory only. Results could not be read back per test. |
| Bug found | `/api/clinical/{aid}/labs` silently dropped kidney and liver markers (creatinine, BUN, ALT, AST) and accepted empty entries. **Fixed.** |
| 3D model | 48 BodyParts3D regions (`assets/anatomy/regions.json`), with mesh names = region ids. Hover/click picking was already in place, and `ares/anatomy/mapping.py` already mapped findings to regions with honesty rules. |
| Health events | Classifier levels, co-deviation patterns (hypoxaemia, respiratory, arrhythmia, hypovolaemia, febrile), incidents with reports, behavioral readiness, lab flags, cabin CO2 attribution, sensor faults |

## 2. Test storage (Phase 1)

The existing `ares_history.db` gets four new tables (schema version 2, via `PRAGMA user_version`). The migration keeps all existing data and carries v0.4 `pvt_runs` over as `legacy` records with their trials.

```
astronaut_profiles (astronaut_id PK, name, role, age, preflight_json, first_seen, updated)
test_sessions      (test_id PK, astronaut_id FK, app_session FK, test_name, test_type, status, started_at,
                    completed_at, duration_s, mission_day, mission_minute, config_json, data_source, created, updated)
test_trials        (test_id FK ON DELETE CASCADE, trial_no, t_offset_ms, isi_ms, rt_ms, outcome, recorded_at,
                    PK(test_id, trial_no))
test_results       (test_id PK FK, metrics_json, scored, score_json, baseline_json, comparison_json,
                    interpretation_json, assessment_json, saved)
indexes: (astronaut_id, started_at), (test_type, started_at), (status), (test_trials.test_id)
```

**Statuses:**

| Status | When it is set |
|---|---|
| `completed` | The test ran to its end |
| `stopped` | Ended early with "Stop & score" |
| `terminated` | Terminate button, page left, or window closed (sent by beacon) |
| `interrupted` | ARES stopped while the test ran; detected at the next start, with partial results kept |
| `legacy` | Saved by v0.4, so the real status is unknown |

A test is never relabelled. Finishing it twice returns the saved record.

**PVT flow:**
1. Start: `POST /api/tests/sessions` opens a record with status `in_progress`.
2. During the test: `POST /api/tests/sessions/{id}/trials` saves each trial as it happens. Re-sent trials are ignored, so nothing is duplicated.
3. End: `POST /api/tests/sessions/{id}/finish` closes the test. The server recomputes every metric from the stored trials, compares it with the previous test and the personal baseline, and saves everything in one transaction. It then reads the record back.

The screen says "Saved to the local database" **only** when that read-back succeeds. If the backend can't be reached, the result is kept on the computer and retried every 10 seconds, and the screen shows "NOT saved yet".

**What gets saved:**

| | Contents |
|---|---|
| **Identification** | Test ID, astronaut, test name and type, session |
| **Timing** | Start, completion, duration, status |
| **Results** | Every trial (outcome, reaction time, interval before, time from start); average, median, fastest, slowest, SD and coefficient of variation; response speed; lapses, misses, false starts, presses with no stimulus |
| **Context** | Configuration, baseline, comparison, interpretation, data source |

Metrics a test did not produce stay empty (`—`) and are never estimated.

**What feeds the alertness model:** only completed, scored PVTs (at least 20 valid responses) and check-ins update the behavioral readiness model and the brain panel. Stopped, terminated and interrupted tests are kept but not scored.

## 3. Test History page (Phase 2)

The **Test History** page (sidebar) lists every record across all sessions.

- **Filters:** astronaut, test type, status and date range. **Export table (CSV)** exports the filtered list.
- **Columns:** date, astronaut, test, duration, average result, status, View.
- **Details:**
  - all metrics, plus a chart and table of the individual trials;
  - comparison with the previous test and the personal baseline (the first 3 completed, scored tests);
  - plain-language interpretation of observed differences;
  - the model assessment, labelled as model output;
  - the performance trend over the mission;
  - **PDF** and **CSV** export (PDF uses matplotlib, which was already a dependency).
- **Longitudinal analysis** (`GET /api/tests/trends`) fits a straight line through the saved, completed tests for average reaction time, lapses and variability:
  - These are labelled **"Observed in saved test results"**. They are not predictions and not a diagnosis.
  - The behavioral readiness level is labelled **"Model-generated assessment"**.
  - A reaction-time result is never described as a brain finding.

## 4. Organ dossiers on the hologram (Phases 3–5)

`GET /api/organs/{region}?astronaut=` returns the dossier for the organ group the clicked mesh belongs to. `GET /api/organs?astronaut=` lists every group with its state; this list feeds "Active findings".

| Group (regions) | Data that drives it | Without data |
|---|---|---|
| Heart (heart) | HR, HRV, BP; patterns arrhythmia / hypoxaemia / hypovolaemia / febrile | grey, "insufficient data" |
| Major blood vessels (aorta, vena cava, arteries, veins) | BP (spot-check) | grey, explained |
| Lungs (left, right, trachea) | SpO2, breathing rate; patterns hypoxaemia / respiratory; cabin CO2 attribution | grey |
| Brain (functional) | Saved reaction tests, check-ins, sleep, behavioral readiness model | — |
| Kidneys / Liver | Lab markers vs the astronaut's own pre-flight value | "No sufficient monitoring data available for this organ." |
| Muscular system (18 muscle regions) | Activity time only + NASA mouse research | message + labelled research |
| Skeletal system (11 bone regions) | Published population average (NASA: 1–1.5 %/month in weight-bearing bones) + mouse research | message + labelled estimate |
| Skin / body temperature | Estimated temperature (body-wide) | grey |
| Digestive organs, spleen, bladder | Not monitored | "No sufficient monitoring data available for this organ." |

**Each event** has the structure below and is listed separately, so two issues in one organ show as two tabs:

```
event_id, astronaut_id, system, anatomical_region, severity, status, detected_at, measurements{current, baseline,
band, difference, z, trend, quality, category}, evidence[], confidence, incident link, recommended_actions[],
long_term_considerations[], data_source
```

**Popup sections:**

| Section | Content | Source |
|---|---|---|
| A — What is happening? | Measurement cards, time of detection, improving or worsening, linked Emergency Command event | Live engine data |
| B — Why was this alert generated? | Evidence lines, each labelled with its data category; detection confidence, uncertainty, sensor reliability; AI predictions (30-min risk, unusual-pattern score, projected state) labelled as AI output | Live engine data |
| C — Immediate action | What to check, extra measurements, whether to notify the crew medical officer, escalation criteria | Verbatim from `knowledge_base/protocols.json` |
| D — Possible long-term effects | Each effect tagged *established*, *spaceflight research* or *possible risk* | `knowledge_base/health_guidance.json` |
| E — Long-term management | Monitoring, follow-up, prevention, trends to watch, escalation | `knowledge_base/health_guidance.json` |
| F — Historical data | Interactive charts against the personal range (this session, up to 12 h); previous alerts (this session and earlier sessions); timeline. For the brain: saved reaction tests and the daily battery. For kidneys and liver: lab history. | Engine history and local databases |

**Data category labels:**
- direct sensor measurement
- derived indicator
- test result
- laboratory marker
- AI prediction
- research evidence (mice)
- population estimate

**Interaction:**
- Hover highlights a structure, and the cursor becomes a pointer.
- Clicking selects the organ, highlights the whole group (for example both lungs) and flies the camera to it. Clicking a red organ opens its active events first.
- The panel is a side panel, so the hologram stays usable. ✕ or **Full body** returns to the full view.
- Severity colours: cyan normal, yellow observation, orange elevated, red critical, grey insufficient data.

## 5. Acceptance results (Linux, offline enforced by a network namespace)

| Check | Result |
|---|---|
| PVT through the UI → saved; close and reopen → still in history; details show all 20 trials; second test → first unchanged | PASS — first test's trials and metrics identical after the second |
| Stopped / Terminated / crash mid-test | Saved as **Stopped early** / **Terminated** / **Interrupted** (5 trials kept); none marked completed |
| No duplicates; re-sent trials; finishing twice | PASS |
| Respiratory abnormality → lungs red → **real 3D click on the right-lung mesh** → Lungs popup | PASS — 2 events (desaturation; tachypnoea), SpO2 85–86 % vs 97.7 %, breathing 19.5–22.5 vs 13, RESP-01 shown, history charts |
| Close → **real click on the heart mesh** | PASS — heart rate event only, no lung data mixed in |
| Two abnormalities (respiratory + kidney lab marker) | PASS — lungs red, kidneys yellow; each popup shows only its own event |
| Brain popup | PASS — latest reaction test vs baseline + all saved tests |
| Unmonitored organ (intestine) | PASS — "No sufficient monitoring data available for this organ." |
| Offline | PASS — no request left the computer; no page errors |
| PVT timing (in-page responder at exactly 250 ms) | 233–249 ms recorded (mean 242 ms) |
| Automated tests | 66 passed, 0 failed |
| 12-scenario desktop offline battery (packaged build) | 12/12 |

**Not verified here:** Windows. These features are platform-independent Python and React, but the Windows desktop build still has to be made and checked on Windows (see `docs/DESKTOP.md`).
