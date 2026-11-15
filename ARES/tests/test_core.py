import numpy as np
import pytest

from ares.processing.ecg import hrv_from_peaks, process_ecg_window
from ares.processing.quality import SignalQualityMonitor
from ares.simulation.ecg import synth_ecg
from ares.simulation.physiology import CrewSimulator
from ares.simulation.profiles import get_crew
from ares.simulation.scenarios import SCENARIO_KEYS, build_scenario
from ares.twin.baseline import PersonalBaseline
from ares.twin.trend import LocalLinearTrend
from ares.twin.twin import DigitalTwin


@pytest.mark.parametrize("hr", [45, 60, 90, 120])
def test_ecg_hr_extraction_accuracy(hr):
    rng = np.random.default_rng(0)
    errs = []
    for _ in range(10):
        sig, _ = synth_ecg(hr, 35, 10, 250, rng=rng)
        out = process_ecg_window(sig, 250)
        errs.append(out["hr"] - hr)
        assert out["quality"] > 0.8
    assert abs(np.mean(errs)) < 2.0


def test_ecg_leadoff_low_quality():
    sig, _ = synth_ecg(70, 40, 10, 250, leadoff=True, rng=np.random.default_rng(1))
    assert process_ecg_window(sig, 250)["quality"] < 0.6


def test_lf_hf_only_for_long_windows():
    peaks = np.cumsum(np.full(20, 250))
    assert hrv_from_peaks(peaks, 250, 10).lf_hf is None


def test_all_scenarios_build():
    for k in SCENARIO_KEYS:
        sc = build_scenario(k, 100)
        assert sc.key == k


def test_quality_flatline_and_fallback():
    m = SignalQualityMonitor()
    r = {"hr": 70, "hrv_rmssd": 40, "spo2": 97, "rr": 14, "sbp": np.nan, "dbp": np.nan, "temp": 36.8}
    for _ in range(10):
        clean, q, faults, meta = m.assess(r, {"spo2_perfusion": 3, "ecg_contact": 1}, 71.0)
    assert "spo2:flatline" in faults and q["spo2"] < 0.1
    m2 = SignalQualityMonitor()
    clean, q, faults, meta = m2.assess(r, {"spo2_perfusion": 3, "ecg_contact": 0}, 72.4)
    assert meta["hr_source"].startswith("oximeter") and clean["hr"] == pytest.approx(72.4)


def test_baseline_learns_and_gates():
    b = PersonalBaseline()
    rng = np.random.default_rng(0)
    for x in rng.normal(55, 2, 500):
        b.update("hr", "rest", x, b.score("hr", "rest", x)["z"])
    s = b.score("hr", "rest", 55)
    assert abs(s["expected"] - 55) < 0.5 and s["scale"] < 3.5
    assert not b.update("hr", "rest", 120, b.score("hr", "rest", 120)["z"])  # gated


def test_trend_detects_slope():
    f = LocalLinearTrend()
    for i in range(240):
        _, sl, sd = f.step(0.05 * i, 1.0)  # +3 units/hour
    assert sl == pytest.approx(3.0, abs=0.6)


def test_twin_flags_scenario_not_normal():
    crew = get_crew()[:1]
    cs = CrewSimulator(crew, seed=1)
    tw = DigitalTwin(crew[0].id)
    for t in range(1440):
        tw.observe(cs.step(t)["AST-1"])
    cs.apply(build_scenario("spo2_drop", 1500), "AST-1")
    zs = []
    for t in range(1440, 1530):
        st = tw.observe(cs.step(t)["AST-1"])
        zs.append(st["z"]["spo2"] or 0)
    assert min(zs[:50]) > -4.5      # before onset
    assert min(zs[70:]) < -6        # after onset
