"""Generate SIMULATED train/test episode datasets (astronaut-level split).

    python scripts/generate_data.py            # full (train 16 + test 6 subjects x 12 scenarios)
    python scripts/generate_data.py --quick    # small smoke-test set
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")   # before numpy/sklearn import (see ares/__init__.py)
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ares.data.generate import DATA_DIR, TEST_ASTRONAUTS, TRAIN_ASTRONAUTS, run_many, specs_for  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tr = range(0, 4) if a.quick else TRAIN_ASTRONAUTS
    te = range(100, 102) if a.quick else TEST_ASTRONAUTS
    print(f"Train subjects {list(tr)} | test subjects {list(te)} (disjoint)")
    train = run_many(specs_for(tr, base_seed=1), a.workers, "train")
    train.to_parquet(DATA_DIR / "train.parquet")
    test = run_many(specs_for(te, base_seed=2), a.workers, "test")
    test.to_parquet(DATA_DIR / "test_rules.parquet")
    print(f"train rows {len(train)}, test rows {len(test)} -> {DATA_DIR}")
