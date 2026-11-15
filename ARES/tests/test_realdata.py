"""Real NASA data analyses: run only when the OSDR files are present."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("OMP_NUM_THREADS", "1")
OSDR = Path(__file__).resolve().parents[1] / "data" / "osdr"
need = pytest.mark.skipif(not (OSDR / "LSDS-7_Complete_Blood_Count_CBC_TRANSFORMED.csv").exists(), reason="OSDR files absent")


@need
def test_i4_qc_catches_column_shift_and_uses_preflight_only():
    from ares.realdata.analysis import i4_model
    r = i4_model()
    assert r["n_crew"] == 4
    assert any(q["crew"] == "C003" and q["tp"] == "L-92" for q in r["qc_excluded_samples"])
    assert 0 <= r["preflight_flag_rate"]["personal_baseline_loo"] < 0.2


@need
def test_soleus_leave_one_mission_out_never_trains_on_test_mission():
    from ares.realdata.analysis import soleus_model
    r = soleus_model()
    assert {x["held_out_mission"] for x in r["leave_one_mission_out"]} == {"RR1", "RR9", "RR18", "BION-M1"}
    assert sum(x["n"] for x in r["leave_one_mission_out"]) == r["n_samples"]


@pytest.mark.skipif(not (OSDR / "radlab_dostel1.csv").exists(), reason="RadLab absent")
def test_radlab_threshold_is_fixed_and_2024_held_out():
    from ares.realdata.analysis import radlab_model
    r = radlab_model()
    assert r["threshold_z"] == 6.0
    assert all(e["split"] == "held-out 2024" for e in r["events"] if e["start"] >= "2024")


def test_provenance_categories_are_the_four_allowed():
    from ares.realdata.provenance import provenance_records
    p = provenance_records()
    allowed = {"REAL NASA DATA", "REAL NON-NASA BIOMEDICAL DATA", "SYNTHETIC SIMULATION DATA"}
    assert all(d["category"] in allowed for d in p["datasets"])
    assert all(m["category"].startswith("MODEL-GENERATED") for m in p["models"])
