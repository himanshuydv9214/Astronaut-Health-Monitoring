# A + B. Critical evaluation and official challenge alignment

## Which official challenge

**NASA Space Apps Challenge 2026 — theme "The Next Frontier" (14–15 November 2026).**
The best-matching official statement is **"Create Health Monitoring Software for Astronauts on Space
Missions"**: software to monitor astronauts' *physical and mental* health on long-duration missions
beyond Earth orbit. NASA's 2026 announcement groups it with the Mars / deep-space challenges that
cover "monitoring physiological and behavioral health indicators" during long-duration travel.

> ARES is **our project name**, not an official challenge. The challenge title above was confirmed
> from several 2026 team repositories and NASA's announcement; the official statement page could
> not be opened from the build environment. **Before submitting, re-read the official statement
> and its listed resources** at spaceappschallenge.org/2026/challenges and adjust wording/datasets.

## Does the original ARES idea fit? Mostly — with three gaps we fixed

| Gap in the original brief | Why it mattered | What we changed |
|---|---|---|
| Almost entirely **physiological** | The challenge explicitly asks for **mental** health too | Added a private **behavioral & cognitive channel**: PVT-B vigilance test (flown on ISS), Samn-Perelli fatigue, mood/stress check-ins, actigraphy sleep debt, personal baselines |
| Treats every abnormality as **one astronaut's illness** | In a closed cabin, a CO₂ build-up makes *everyone* breathe faster | Added **cabin environment intelligence** (ppCO₂ vs NASA-STD-3001 3 mmHg limit) with **crew-wide attribution** |
| Implied **continuous immune sensing** | Immune markers need lab analysis; wearables can't measure them | Added **symptom + lab logging** compared with each astronaut's *own* pre-flight values, used as corroborating evidence |

## Honest critique of the brief (what we deliberately did NOT do)

1. **"Predict emerging health risks" with deep learning on astronaut data.** There is no public,
   labelled dataset of in-flight astronaut emergencies. Anything trained to "predict emergencies"
   learns the data generator. We therefore:
   - keep the **emergency classifier rule-based and auditable** (ML may only raise *observation*),
   - train ML on simulation **and say so on every screen and report**,
   - measure **generalisation to unseen people and unseen emergency types**, not just accuracy.
2. **LSTM / Transformer models.** With 1-minute vitals and simulated labels, a gradient-boosted model
   on engineered temporal features is the right size; a sequence model adds training cost and
   opacity without evidence of benefit. Listed in the roadmap, evaluated only against real data.
3. **Individual cancer / cardiovascular / cataract risk from radiation** (team radiation note's goal).
   Two astronauts with the same dose can have different outcomes, as the note itself says, and
   short-term dosimetry cannot predict an individual's cancer. ARES keeps **measured**, **modelled**
   and **inferred** separate, reports dose against NASA-STD-3001 limits, and labels biological risk
   "not computed". A population-level projection from NASA's published risk models (with uncertainty)
   is a roadmap item, clearly labelled as population-level.
4. **"Recommended treatment" from generative AI.** Not done. The assistant is **retrieval-only** and
   returns knowledge-base entries verbatim with their source and approval status.
5. **Claims about spacecraft hardware.** None. We report measured inference latency on a laptop CPU
   (single-threaded) and list what would run onboard vs on Earth.

## Mapping to the judging criteria named in our brief (verify on the official judging page)

| Criterion | Evidence in ARES |
|---|---|
| **Impact** | Earth-independent operation (blackout mode), false-alarm reduction vs conventional limits (see `reports/EVALUATION.md`), environment-vs-illness attribution, privacy-preserving behavioral health |
| **Creativity** | Personal context-conditioned Bayesian baselines; corroboration rule (population limits weighted by personal deviation); crew-wide CO₂ attribution; live PVT-B in the dashboard; tamper-evident onboard record |
| **Validity** | Real-data validation on PhysioNet MIT-BIH (cardiologist-annotated) and drivedb; astronaut-level held-out evaluation; baselines (static limits, NEWS2, logistic regression, max-z); calibration; leave-one-scenario-out; every threshold labelled *published* or *engineering choice* |
| **Relevance** | Direct answer to the official challenge (physical + mental health, long-duration, beyond LEO); uses NASA standards (NASA-STD-3001), NASA/partner data (DONKI, OSDR resources), ISS-flown instruments (PVT-B) |
| **Presentation** | Mission-control dashboard with 6 views, 13 injectable scenarios, live demo script (`docs/DEMO_SCRIPT.md`) |

## How the team's research notes were used

| Team note | Used for |
|---|---|
| Cardiovascular | HR, HRV, BP, ECG pipeline; arrhythmia and fluid-loss patterns; BP-cuff repeat-measurement rule |
| Behavioral health | Behavioral channel design, **privacy rule** (astronaut + CMO only; Earth gets category only), countermeasure entry BEH-01 |
| Closed environment | Cabin module, CO₂ limits, crew-wide attribution, ENV-01 protocol, CO₂ scenario |
| Immune | Symptom + lab log with personal pre-flight baselines; fever report corroborates temperature deviation; "abnormal marker ≠ diagnosis" wording |
| Radiation | Measured / modelled / inferred separation; CAD/RAD discussion ("exposure ≠ biological damage") in the docs; individual-risk prediction moved to roadmap (see critique 3) |
| Microgravity | Longitudinal drift from mission reference in the digital twin; bone/muscle/SANS assessments listed as roadmap inputs to the clinical log (periodic, not wearable) |
