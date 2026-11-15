# F. Two-day hackathon MVP vs longer-term research roadmap

## What is in the MVP (this repository)
- End-to-end pipeline: acquisition (simulated) → signal processing → digital twin → ML → emergency
  classification → reports/protocols → mission-aware comms, all offline.
- 4 fictional crew, 13 injectable scenarios (12 physiological/environmental + behavioral strain + cabin CO₂).
- Behavioral channel with a working PVT-B; symptoms and lab logging; cabin environment module.
- Models trained on 16 synthetic subjects, evaluated on 6 others; full evaluation report.
- Real-data validation of the ECG chain on PhysioNet recordings.
- Dashboard (6 views), REST API, Docker, tests.

## Suggested split for a 5-person team over the 48 hours
| Person | Owns | Demo moment |
|---|---|---|
| 1 | Story + slides + challenge alignment (`docs/01`) | Problem: "Earth is 20 minutes away" |
| 2 | Digital twin + classifier (explain personal baselines, corroboration rule) | Athlete's HR 42 is *not* an alarm |
| 3 | ML + evaluation (`reports/EVALUATION.md`) | False alarms vs static limits; calibration plot |
| 4 | Behavioral + clinical + privacy | Live PVT-B on stage |
| 5 | Mission/comms + cabin + radiation; demo driver | Blackout emergency; CO₂ attribution |

## Roadmap (after the hackathon)
| Horizon | Work | Why |
|---|---|---|
| Weeks | Run `scripts/fetch_data.py` (DONKI, all 48 MIT-BIH records); report full MIT-BIH beat-detection statistics | Replace 1-record demo with a standard benchmark |
| Weeks | Replay real ISS cabin CO₂ (OSDR Environmental Data App) and RadLab dosimetry into the simulator | Real environment streams |
| Weeks | Use Inspiration4 CBC/metabolic data (OSDR) to set realistic pre/post-flight lab deltas for the immune module | Real human spaceflight labs |
| Months | Analog validation: HERA / CHAPEA-like data via NASA data request (LSDA) or an analog partner | First test on confined crews |
| Months | Multi-lead / personal-template ECG quality index | The SQI weakness found below 3 dB SNR |
| Months | Sequence models (TCN/Transformer) **only** if they beat the GBM on real analog data | Avoid complexity without evidence |
| Months | Population-level radiation risk projection from NASA's published risk models, with uncertainty bands, labelled as population-level | Team radiation goal, done honestly |
| Months | Periodic assessments (ultrasound, bone/muscle tests, vision/SANS checks) in the clinical log | Team microgravity note |
| Long | Flight-surgeon-approved protocol knowledge base; human-factors evaluation of alerts; safety case for Class-A software | Required before any operational use |
