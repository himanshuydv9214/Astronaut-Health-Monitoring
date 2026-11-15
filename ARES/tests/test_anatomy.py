"""Honesty rules of the 3D anatomical mapping + asset integrity."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "anatomy"


@pytest.fixture(scope="module")
def engine():
    from ares.engine import AresEngine
    e = AresEngine()
    for _ in range(5):
        e.tick()
    return e


def test_glb_nodes_match_regions_json():
    trimesh = pytest.importorskip("trimesh")
    regions = json.loads((ASSETS / "regions.json").read_text())["regions"]
    scene = trimesh.load(ASSETS / "ares_body.glb", force="scene")
    names = {n.split("_")[0] if n.split("_")[-1].isdigit() else n for n in scene.geometry}
    ids = {r["id"] for r in regions}
    assert ids <= {n.rsplit("_", 1)[0] if n.rsplit("_", 1)[-1].isdigit() else n for n in scene.geometry} | names | set(scene.geometry)
    assert {"heart", "lung_left", "lung_right", "soleus_left", "tibia_left", "skin"} <= ids


def test_unmonitored_organs_are_not_called_normal(engine):
    from ares.anatomy.mapping import region_states
    s = region_states(engine, engine.crew[0].id)
    for rid in ("stomach", "spleen", "bladder", "intestine_small"):
        assert s["regions"][rid]["state"] == "not_monitored"


def test_lung_highlight_requires_respiratory_signal(engine):
    from ares.anatomy.mapping import region_states
    aid = engine.crew[1].id
    engine.trigger("spo2_drop", aid)
    for _ in range(40):
        engine.tick()
    s = region_states(engine, aid)
    assert s["regions"]["lung_left"]["state"] in ("elevated", "critical")
    assert {m["key"] for m in s["regions"]["lung_left"]["metrics"]} <= {"spo2", "rr"}
    assert s["focus"] and s["focus"]["region"] in ("lung_left", "lung_right", "trachea", "heart")
    # kidneys must not light up from a respiratory event
    assert s["regions"]["kidney_left"]["state"] in ("normal", "not_monitored", "unknown")
    engine.clear_scenarios()


def test_brain_is_functional_not_a_finding(engine):
    from ares.anatomy.mapping import region_states
    s = region_states(engine, engine.crew[0].id)
    assert s["regions"]["brain"]["kind"] == "functional"


def test_radiation_is_an_overlay_not_an_organ_claim(engine):
    from ares.anatomy.mapping import region_states
    s = region_states(engine, engine.crew[0].id)
    assert "radiation" in s["overlays"] and "No organ-specific injury" in s["overlays"]["radiation"]["note"]
    assert all(r["kind"] != "exposure" for r in s["regions"].values())


def test_research_evidence_never_sets_astronaut_state(engine):
    from ares.anatomy.mapping import region_states, research_evidence
    if not research_evidence():
        pytest.skip("real-data report not generated")
    s = region_states(engine, engine.crew[0].id)
    sol = s["regions"]["soleus_left"]
    assert sol["research_evidence"] and sol["state"] == "not_monitored" and sol["kind"] == "organism_evidence"
    assert "NOT a measurement" in sol["note"]
