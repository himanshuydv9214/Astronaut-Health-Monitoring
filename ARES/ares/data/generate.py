"""Episode generation for training and evaluation (ALL DATA SIMULATED).

An *episode* = one synthetic astronaut, a 2-day baseline-acquisition period
(never scored), a random nominal lead-in, one injected scenario, and a
follow-up window. Episodes run through the real `AresEngine`, so what is
evaluated is exactly what the dashboard runs.

Split design (prevents leakage):
  * astronaut-level split - train / test use DISJOINT synthetic people;
  * each episode is a contiguous, chronologically ordered stream; rows from
    one episode never appear in two splits;
  * forecaster labels look forward in time only within the same episode.
"""

from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ares.config import VITAL_KEYS
from ares.intelligence.features import FEATURE_NAMES
from ares.simulation.profiles import random_profile
from ares.simulation.scenarios import SCENARIO_KEYS

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"

# Follow-up after onset (minutes). Slow scenarios need longer windows.
FOLLOW_MIN = {"sleep_deprivation": 4 * 1440, "gradual_deterioration": 900, "normal": 1440}
DEFAULT_FOLLOW = 600
HORIZON_MIN = 30   # forecaster horizon


@dataclass(frozen=True)
class EpisodeSpec:
    astronaut_index: int
    scenario: str
    seed: int
    load_models: bool = False


def run_episode(spec: EpisodeSpec) -> pd.DataFrame:
    from ares.engine import AresEngine   # local import: worker processes

    rng = np.random.default_rng(spec.seed)
    prof = random_profile(spec.astronaut_index)
    eng = AresEngine(crew=[prof], seed=spec.seed, demo_start_day=float(rng.uniform(20, 240)),
                     baseline_days=2.0, with_ecg=False, load_models=spec.load_models, record_truth=True)
    lead = int(rng.integers(60, 12 * 60))
    for _ in range(lead):
        eng.tick()
    onset = eng.t + 1
    if spec.scenario != "normal":
        eng.trigger(spec.scenario, prof.id)
    for _ in range(FOLLOW_MIN.get(spec.scenario, DEFAULT_FOLLOW)):
        eng.tick()
    rows = []
    for r in eng.truth_log:
        row = {"t": r["t"], "aid": r["aid"], "pred": r["pred"], "cand": r["cand"], "truth": r["truth"],
               "events": "|".join(r["events"]), "faults": "|".join(r["faults"]), "risk": r["risk"],
               "anomaly": r["anomaly"], "news2": r["news2"], "ctx": r["ctx"], "sensor_alert": r["sensor_alert"],
               "spe": r.get("spe", False)}
        for k in VITAL_KEYS:
            row[f"v_{k}"] = r["v"][k]
            row[f"age_{k}"] = r["age"][k]
        for f in FEATURE_NAMES:
            row[f] = r["feats"].get(f, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows)
    df["scenario"] = spec.scenario
    df["episode"] = f"{spec.scenario}:{spec.astronaut_index}:{spec.seed}"
    df["astronaut_index"] = spec.astronaut_index
    df["onset"] = onset
    df["min_since_onset"] = df["t"] - onset
    # forecaster target: truth level >= 2 at any time in (t, t+H]
    tr = df["truth"].to_numpy()
    fut = np.zeros(len(df), dtype=int)
    hi = (tr >= 2).astype(int)
    csum = np.concatenate([[0], np.cumsum(hi)])
    for i in range(len(df)):
        j = min(len(df), i + 1 + HORIZON_MIN)
        fut[i] = int(csum[j] - csum[i + 1] > 0)
    df["y_future"] = fut
    return df


def run_many(specs: list[EpisodeSpec], workers: int = 2, label: str = "") -> pd.DataFrame:
    t0 = time.time()
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, df in enumerate(ex.map(run_episode, specs, chunksize=1)):
            out.append(df)
            if (i + 1) % 12 == 0 or i + 1 == len(specs):
                print(f"  [{label}] {i + 1}/{len(specs)} episodes ({time.time() - t0:.0f}s)", flush=True)
    return pd.concat(out, ignore_index=True)


def specs_for(astronauts: range, seeds_per: int = 1, base_seed: int = 0, load_models: bool = False,
              scenarios: list[str] = SCENARIO_KEYS) -> list[EpisodeSpec]:
    return [EpisodeSpec(a, sc, base_seed + 1000 * a + 37 * j + i, load_models)
            for a in astronauts for j, sc in enumerate(scenarios) for i in range(seeds_per)]


# Disjoint synthetic populations
TRAIN_ASTRONAUTS = range(0, 16)
TEST_ASTRONAUTS = range(100, 106)
