"""Data provenance records for every dataset and model shown in ARES.

Four categories are never mixed:
  REAL NASA DATA · REAL NON-NASA BIOMEDICAL DATA · SYNTHETIC SIMULATION DATA · MODEL-GENERATED ESTIMATES

A dataset's status is computed from what is actually on disk, so the dashboard
can never claim a model was trained on data that is not present.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OSDR_DIR = ROOT / "data" / "osdr"
REPORTS = ROOT / "reports"

DATASETS = [
    {"id": "OSD-569", "title": "Inspiration4 whole blood: complete blood count (CBC)", "category": "REAL NASA DATA",
     "source": "NASA OSDR (ALSDA LSDS-7)", "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-569",
     "population": "4 civilian astronauts (SpaceX Inspiration4, 3-day LEO mission)",
     "timepoints": "L-92, L-44, L-3, R+1, R+45, R+82, R+194 days", "files": ["LSDS-7_Complete_Blood_Count_CBC_TRANSFORMED.csv"],
     "use": "Model E: personal-baseline deviation on real astronaut blood counts", "supervised": False,
     "limitations": "n = 4; short mission; no in-flight blood draws in this file; civilians, not career astronauts."},
    {"id": "OSD-575", "title": "Inspiration4 serum: comprehensive metabolic panel + immune/cardiac cytokine arrays",
     "category": "REAL NASA DATA", "source": "NASA OSDR (ALSDA LSDS-8)",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-575", "population": "4 civilian astronauts",
     "timepoints": "L-92, L-44, L-3, R+1, R+45, R+82, R+194 days",
     "files": ["LSDS-8_Comprehensive_Metabolic_Panel_CMP_TRANSFORMED.csv",
               "LSDS-8_Multiplex_serum_immune_EvePanel_TRANSFORMED.csv"],
     "use": "Model E: kidney/liver/electrolyte markers and 71 serum cytokines vs own pre-flight baseline", "supervised": False,
     "limitations": "n = 4; markers are not organ imaging; multiplex arrays are research assays."},
    {"id": "OSD-662", "title": "Mouse soleus after spaceflight (RR-1, RR-9, RR-18, Bion-M1) and hindlimb unloading",
     "category": "REAL NASA DATA", "source": "NASA OSDR (ALSDA LSDS-75)",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-662",
     "population": "101 mouse samples: 28 flight, 28 habitat ground, 27 vivarium, 18 ground-study",
     "files": ["LSDS-75_western-blot_soleus_westernblot_TRANSFORMED.csv"],
     "use": "Model C: spaceflight soleus response, leave-one-mission-out", "supervised": True,
     "limitations": "Mice, not humans: shown only as research evidence on the soleus, never as astronaut risk."},
    {"id": "OSD-654", "title": "Mouse tibia microCT + DXA after RR-9 spaceflight and hindlimb unloading",
     "category": "REAL NASA DATA", "source": "NASA OSDR (ALSDA LSDS-66)",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-654", "population": "35 mouse samples (5 flight)",
     "files": ["LSDS-66_microCT_uCT_TRANSFORMED.csv"],
     "use": "Model C: bone microstructure evidence on the tibia", "supervised": False,
     "limitations": "Mice; small groups; organism-level evidence only."},
    {"id": "OSD-663", "title": "Mouse femur western blot (GSK3-beta) after RR-9 spaceflight and hindlimb unloading",
     "category": "REAL NASA DATA", "source": "NASA OSDR (ALSDA LSDS-70)",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-663", "population": "39 mouse samples (6 flight)",
     "files": ["LSDS-70_western-blot_Western_blot_femur_TRANSFORMED.csv"],
     "use": "Model C: bone evidence on the femur", "supervised": False, "limitations": "Mice; small groups."},
    {"id": "RadLab-DosTel1", "title": "ISS DOSTEL-1 absorbed dose rate (OSDR RadLab)", "category": "REAL NASA DATA",
     "source": "NASA OSDR RadLab (ASI/DLR DOSTEL data)", "url": "https://visualization.osdr.nasa.gov/radlab/",
     "files": ["radlab_dostel1.csv"], "use": "Model D: exposure anomaly / SPE detection on a real dosimeter",
     "supervised": False, "limitations": "ISS orbit inside the magnetosphere; not deep-space dose."},
    {"id": "SRAG-SEP", "title": "NASA JSC Space Radiation Analysis Group solar proton event list", "category": "REAL NASA DATA",
     "source": "NASA JSC SRAG, distributed in github.com/ktindiana/fetchsep (reference/SRAG_SEP_List.csv)",
     "url": "https://github.com/ktindiana/fetchsep", "files": ["../external/SRAG_SEP_List.csv"],
     "population": "33 events (GOES >10 MeV) between Mar 2022 and Oct 2024",
     "use": "Event labels for Model D evaluation (2024 held out)", "supervised": False,
     "limitations": "Measured at geostationary orbit, not dose inside the ISS."},
    {"id": "GLDS-104 / GLDS-673", "title": "GeneLab RNA-seq runsheets: mouse soleus RR-1 (OSD-104) and RR-23 (OSD-770)",
     "category": "REAL NASA DATA", "source": "NASA GeneLab", "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-104",
     "population": "OSD-104: 6 flight / 6 ground; OSD-770: 10 flight / 10 ground / 10 vivarium libraries",
     "files": ["GLDS-104_rna_seq_bulkRNASeq_v2_runsheet.csv", "GLDS-673_rna_seq_bulkRNASeq_v2_runsheet.csv"],
     "use": "Sample design only (metadata). Expression model needs the normalised-counts table (roadmap).",
     "supervised": False, "limitations": "No expression values in these files."},
    {"id": "PhysioNet-mitdb-100", "title": "MIT-BIH Arrhythmia Database (record 100 in repo)",
     "category": "REAL NON-NASA BIOMEDICAL DATA", "source": "PhysioNet (ODC-By 1.0)",
     "url": "https://physionet.org/content/mitdb/1.0.0/", "files": ["../external/mitdb/100.dat"],
     "use": "Validation of the ECG signal chain (reports/REAL_DATA_VALIDATION.md)", "supervised": False,
     "limitations": "Hospital ECG from 1975-79, Earth gravity."},
    {"id": "ARES-sim", "title": "ARES crew physiology simulator", "category": "SYNTHETIC SIMULATION DATA",
     "source": "This project (ares/simulation)", "url": "", "files": [],
     "use": "Live demo stream, emergency scenarios, Model A training/evaluation", "supervised": True,
     "limitations": "Labels defined by the scenario designer; tests logic, not clinical validity."},
]

MODELS = [
    {"id": "A", "name": "Vital-sign anomaly detection + 30-min risk forecaster", "data": ["ARES-sim"],
     "category": "MODEL-GENERATED ESTIMATE (trained on SYNTHETIC SIMULATION DATA)",
     "method": "Isolation Forest (nominal-only) + gradient boosting with isotonic calibration; vs OC-SVM, LOF, autoencoder",
     "validation": "Astronaut-level held-out split, leave-one-scenario-out", "report": "reports/EVALUATION.md"},
    {"id": "E", "name": "Personal baseline on real astronaut labs", "data": ["OSD-569", "OSD-575"],
     "category": "MODEL-GENERATED ESTIMATE on REAL NASA DATA",
     "method": "Per-astronaut pre-flight baseline (L-92/L-44/L-3) -> deviation at R+1..R+194 vs generic range",
     "validation": "Pre-flight leave-one-out false-flag rate; generic range vs personal baseline; row-level QC", "report": "reports/REAL_NASA_DATA.md"},
    {"id": "C", "name": "Spaceflight musculoskeletal response (mouse)", "data": ["OSD-662", "OSD-654", "OSD-663"],
     "category": "MODEL-GENERATED ESTIMATE on REAL NASA DATA (organism-level)",
     "method": "Flight vs ground effect sizes; logistic regression on MHC I/IIa/IIx vs single MHC IIx rule",
     "validation": "Leave-one-mission-out", "report": "reports/REAL_NASA_DATA.md"},
    {"id": "D", "name": "Radiation exposure anomaly detection", "data": ["RadLab-DosTel1", "SRAG-SEP"],
     "category": "MODEL-GENERATED ESTIMATE on REAL NASA DATA",
     "method": "SAA-excluded 3-h 90th-percentile dose, robust z vs trailing 7 days, alarm z >= 6",
     "validation": "Against SRAG events; 2022-23 development, 2024 held out",
     "report": "reports/REAL_NASA_DATA.md"},
]


def _status(d: dict) -> str:
    if not d["files"]:
        return "in use"
    present = [f for f in d["files"] if (OSDR_DIR / f).exists()]
    if len(present) == len(d["files"]):
        return "loaded"
    return "partially loaded" if present else "awaiting data file(s)"


def provenance_records() -> dict:
    ds = [d | {"status": _status(d)} for d in DATASETS]
    by = {d["id"]: d["status"] for d in ds}
    models = []
    for m in MODELS:
        st = [by.get(x, "?") for x in m["data"]]
        status = "trained / evaluated" if all(s in ("loaded", "in use") for s in st) else \
            "partially available" if any(s in ("loaded", "partially loaded") for s in st) else "awaiting data"
        rep = ROOT / m["report"]
        models.append(m | {"status": status, "report_exists": rep.exists()})
    extra = REPORTS / "real_nasa_data.json"
    return {"categories": ["REAL NASA DATA", "REAL NON-NASA BIOMEDICAL DATA", "SYNTHETIC SIMULATION DATA",
                           "MODEL-GENERATED ESTIMATES"],
            "datasets": ds, "models": models,
            "results": json.loads(extra.read_text()) if extra.exists() else None,
            "anatomy_asset": {"source": "BodyParts3D, (c) The Database Center for Life Science",
                              "license": "CC BY 4.0", "processing": "simplified for real-time display",
                              "mirror": "github.com/Kevin-Mattheus-Moerman/BodyParts3D"}}
