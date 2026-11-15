# C. Scientific grounding and NASA / partner data

## Key scientific and operational references used in the design

| Topic | Reference | Where it is used |
|---|---|---|
| Earth-independent medical operations | NASA EIMO technical interchange (NTRS 20240001278): ML needs large datasets; CDSS may be Class-A safety-critical; COTS hardware radiation failures | Rule-based classifier, ML limited to observation, retrieval-only assistant |
| GCR dose rate in cruise / on Mars | Zeitlin et al., *Science* 2013 (MSL/RAD ≈1.84 mSv/day cruise); Hassler et al., *Science* 2014 (≈0.64 mSv/day surface) | Modelled dose, SPE detection ratio |
| Radiation limits | NASA-STD-3001 Vol 1 (career effective dose 600 mSv) | Dose dashboard |
| Cabin CO₂ | NASA-STD-3001 Vol 2 [V2 6004]: 1-h mean ppCO₂ ≤ 3 mmHg; OCHMO-TB-004: 7-day mean < 2.5 mmHg keeps headache risk < 1 % | Cabin module + ENV-01 |
| Cabin temperature / humidity | NASA-STD-3001 Vol 2 [V2 6013]: 20–25 °C, 30–60 % RH | Cabin module |
| Vigilance | Basner, Mollicone & Dinges, *Acta Astronautica* 2011 (PVT-B, 355 ms lapse); Jones, Basner et al., *SLEEP* 2022 (ISS Reaction Self Test: false start < 130 ms, response speed primary) | Behavioral channel + live test |
| Cognition in analogs | Basner et al. 2020, HERA confinement & sleep restriction (Cognition battery) | Justifies behavioral monitoring in confinement |
| Sleep-loss dose–response | Van Dongen et al., *SLEEP* 2003 | Shape (not magnitude) of simulated PVT decline |
| Early-warning score | Royal College of Physicians, NEWS2 (2017) | Published comparator baseline |
| R-peak detection | Pan & Tompkins, *IEEE TBME* 1985 | ECG pipeline |
| HRV standards | Task Force ESC/NASPE, *Circulation* 1996 (spectral HRV needs ≥ 2–5 min) | LF/HF only on long windows |
| Small-n spaceflight data | NASA HRP Artemis II Human Research Data Methodology Challenge (4 crew, many systems) | Personal baselines rather than population models |

## Datasets

**Bottom line:** there is no open dataset of continuous in-flight astronaut vitals with labelled
emergencies. Astronaut clinical data are privacy-protected and released by request. ARES therefore
uses (1) real NASA space-environment data, (2) real human physiological recordings from ground
datasets to validate signal processing, and (3) a documented simulator for emergencies, and keeps
the three visibly separate.

| # | Dataset | Source | Access | Variables | Size / sampling | Limitations | License | Use in ARES |
|---|---|---|---|---|---|---|---|---|
| 1 | **DONKI – Solar Energetic Particle events** | NASA CCMC / NASA Open APIs | `kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/SEP` (no key) or `api.nasa.gov/DONKI/SEP` (API key) | sepID, eventTime, instruments, linked CME/flare IDs | Event list (~tens per year) | Event catalogue near Earth, **not** dose at a Mars-bound vehicle | US Gov work | `ares/radiation/donki.py`; cached offline; shown in radiation panel; event timing for SPE scenario (never converted to crew dose) |
| 2 | **MIT-BIH Arrhythmia Database** | PhysioNet (Moody & Mark) | physionet.org/content/mitdb/1.0.0 (also AWS open data) | 2-lead ECG, beat annotations by ≥2 cardiologists | 48 × 30 min, 360 Hz, ~110 000 beats | Hospital patients 1975-79, Earth gravity | ODC-By 1.0 | **Real-data validation** of R-peak detection, HR, RMSSD, noise robustness (`scripts/validate_real_data.py`) |
| 3 | **Stress Recognition in Automobile Drivers (drivedb)** | PhysioNet (Healey & Picard 2005) | physionet.org/content/drivedb | ECG, HR, respiration, GSR, EMG | ~1-1.5 h per drive; ECG ~496 Hz | Driving stress ≠ spaceflight stress; marker channel needs protocol notes | ODC-By 1.0 (check page) | Real ambulatory ECG: agreement of ARES HR with device HR; ground analog for noisy, stressed wear |
| 4 | **NASA OSDR** (GeneLab + Ames Life Sciences Data Archive) | NASA Ames | osdr.nasa.gov; Biological Data API `visualization.osdr.nasa.gov/biodata/api`; AWS `s3://nasa-osdr` | Omics + phenotypic/physiological studies (mostly model organisms) | Hundreds of studies | Mostly non-human; not continuous vitals | No restrictions (AWS registry) | Roadmap: biological context for radiation/immune modules; cite in research |
| 5 | **Inspiration4 human data in OSDR** (e.g. blood datasets OSD-569/570/571/575) | NASA OSDR / Weill Cornell (SOMA) | OSDR study pages + API | CBC, metabolic panels, immune/cytokine and omics, pre/in/post-flight | 4 civilians, 3-day LEO mission | Tiny n, short mission; processed data public, raw genetic data by application | OSDR terms | **Best open source for the immune/lab module**: realistic pre/post-flight lab deltas and personal-baseline method (next step) |
| 6 | **OSDR RadLab** | NASA OSDR + partner agencies (ASI DORELI: DOSTEL1/2, Lidal, REM; Bulgarian Liulin-5) | visualization.osdr.nasa.gov/radlab + RadLab API | Absorbed dose rate, flux, by detector/module/time | Time series | ISS (LEO, inside magnetosphere) – not deep space | OSDR terms | Roadmap: replace simulated dosimeter with replayed real ISS dosimetry |
| 7 | **OSDR Environmental Data Application** | NASA OSDR | visualization.osdr.nasa.gov | ISS cabin temperature, RH, **CO₂**, radiation during Rodent Research missions | Mission telemetry | Specific missions only | OSDR terms | Roadmap: replay real ISS CO₂ telemetry in the cabin module |
| 8 | **NASA LSDA / LSAH** (Life Sciences Data Archive; Lifetime Surveillance of Astronaut Health) | NASA JSC / HRP | Data request via NASA Life Sciences Portal | Astronaut + flight-analog research data; clinical data | Large | **Restricted** – request + data-use agreement; privacy-protected | Restricted | Not used in the hackathon; the path to real validation (with flight-surgeon partners) |
| 9 | **NOAA SWPC GOES integral protons** | NOAA SWPC | services.swpc.noaa.gov/json/goes/… | >10 MeV proton flux, 5-min | Rolling 1–7 days | Earth orbit vantage | US Gov work | Roadmap: live SPE onset signal alongside DONKI |

### What was actually fetched in this build
The build machine could reach only GitHub, so: MIT-BIH record **100** and drivedb **drive02** came
from the `MIT-LCP/wfdb-python` sample-data mirror (byte-identical PhysioNet files). DONKI could not be
reached; the cache is empty until `python scripts/fetch_data.py` is run with internet.

### Simulated data (labelled as such everywhere)
- Crew physiology, dosimeters, cabin sensors, behavioral tests: `ares/simulation`, `ares/behavioral/simulate.py`,
  `ares/environment/cabin.py`. Model per signal = personal baseline + activity (lagged) + circadian +
  AR(1) + scenario effects + measurement error + artefacts/faults.
- The fast simulation path reproduces the **measured** error of the ECG pipeline (HR ≈ 1.7 %, 10-s RMSSD
  lognormal, log-sd ≈ 1.05/√(beats−1)), fitted by running the synthetic ECG through the real
  processing chain, so training data, baselines and the live ECG dashboard are statistically consistent.
- Ground-truth labels are defined by the scenario designer (`ares/simulation/scenarios.py`); the
  pipeline never sees them.
