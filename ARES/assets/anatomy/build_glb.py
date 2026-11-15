"""Build ares_body.glb from BodyParts3D meshes (one named node per anatomical region).

Source data: BodyParts3D (c) The Database Center for Life Science, licensed under
CC BY 4.0 (licence updated 2025-02-27; earlier releases CC BY-SA 2.1 JP). STL files
from the Kevin-Mattheus-Moerman/BodyParts3D GitHub mirror (release 3.0, 95 % polygon
reduction, converted OBJ->STL). See ATTRIBUTION.md.

    python assets/anatomy/build_glb.py --fetch      # download the needed STLs (~530 MB, GitHub)
    python assets/anatomy/build_glb.py              # build ares_body.glb + regions.json

Processing: merge the atomic BodyParts3D meshes of each region, decimate to a
per-region triangle budget (quadric decimation), convert mm -> m and Z-up ->
Y-up with the body facing +Z, place the feet at y = 0. Geometry is otherwise
unchanged: this is BodyParts3D anatomy, simplified for real-time display.
"""
import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STL_DIR = HERE / "_stl_cache"
MIRROR = "https://raw.githubusercontent.com/Kevin-Mattheus-Moerman/BodyParts3D/main/assets/BodyParts3D_data/stl/"

# triangle budget per region (whole model ~ 330k triangles)
BUDGET = {"skin": 70000, "brain": 22000, "heart": 14000, "lung_left": 8000, "lung_right": 8000, "liver": 7000,
          "skeleton_other": 30000, "skull": 14000, "spine": 18000, "ribcage": 12000, "pelvis": 6000,
          "arteries": 9000, "veins": 7000}
LAYER_DEFAULT = {"organs": 4000, "vessels": 4000, "skeleton": 5000, "muscles": 3500, "skin": 70000}


def fetch(manifest):
    STL_DIR.mkdir(exist_ok=True)
    parts = sorted({p for r in manifest for p in r["parts"]})

    def get(p):
        dest = STL_DIR / f"{p}.stl"
        if dest.exists() and dest.stat().st_size > 0:
            return True
        try:
            with urllib.request.urlopen(MIRROR + f"{p}.stl", timeout=120) as r:
                dest.write_bytes(r.read())
            return True
        except Exception as e:  # noqa: BLE001
            print("  !", p, e)
            return False
    with ThreadPoolExecutor(12) as ex:
        ok = sum(ex.map(get, parts))
    print(f"fetched {ok}/{len(parts)} meshes")


def build(manifest, out_glb: Path, out_json: Path, stl_dir: Path):
    import fast_simplification
    import trimesh

    rot = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)   # (x, y, z) -> (x, z, -y): Z-up -> Y-up, front -Y -> +Z
    skin = trimesh.load(stl_dir / "FMA7163.stl")
    b = skin.bounds
    offset = np.array([-(b[0][0] + b[1][0]) / 2, -(b[0][1] + b[1][1]) / 2, -b[0][2]])   # centre x,y; feet at 0
    scene = trimesh.Scene()
    regions_out = []
    total = 0
    for r in manifest:
        meshes = []
        for p in r["parts"]:
            f = stl_dir / f"{p}.stl"
            if f.exists():
                meshes.append(trimesh.load(f))
        if not meshes:
            print("  ! no meshes for", r["id"])
            continue
        m = trimesh.util.concatenate(meshes)
        m.merge_vertices()
        target = BUDGET.get(r["id"], LAYER_DEFAULT[r["layer"]])
        if len(m.faces) > target:
            v, f = fast_simplification.simplify(m.vertices.astype(np.float32), m.faces.astype(np.int32),
                                                target_reduction=1 - target / len(m.faces), agg=6)
            m = trimesh.Trimesh(v, f, process=True)
        m.vertices = ((m.vertices + offset) / 1000.0) @ rot.T
        m.fix_normals() if r["id"] != "skin" else None   # skin has inner surfaces; keep winding as-is
        total += len(m.faces)
        c = m.bounds.mean(axis=0)
        scene.add_geometry(m, node_name=r["id"], geom_name=r["id"])
        regions_out.append({k: r[k] for k in ("id", "label", "layer", "system")} | {
            "bodyparts3d_ids": r["parts"], "triangles": int(len(m.faces)),
            "center": [round(float(x), 4) for x in c],
            "size": [round(float(x), 4) for x in (m.bounds[1] - m.bounds[0])]})
        print(f"  {r['id']:22s} {len(r['parts']):4d} parts -> {len(m.faces):6d} tris")
    out_glb.write_bytes(scene.export(file_type="glb"))
    out_json.write_text(json.dumps({
        "source": "BodyParts3D (c) The Database Center for Life Science, CC BY 4.0",
        "mirror": "github.com/Kevin-Mattheus-Moerman/BodyParts3D (release 3.0, obj_95 -> STL)",
        "processing": "regions merged from atomic meshes, quadric-decimated, mm->m, Z-up->Y-up, facing +Z",
        "total_triangles": int(total), "regions": regions_out}, indent=1))
    print(f"wrote {out_glb} ({out_glb.stat().st_size / 1e6:.1f} MB, {total:,} triangles)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--stl-dir", default=str(STL_DIR))
    ap.add_argument("--out", default=str(HERE / "ares_body.glb"))
    a = ap.parse_args()
    man = json.loads((HERE / "regions_manifest.json").read_text())
    if a.fetch:
        fetch(man)
        if a.stl_dir == str(STL_DIR) and not any(STL_DIR.glob("*.stl")):
            sys.exit(1)
    build(man, Path(a.out), Path(a.out).with_name("regions.json"), Path(a.stl_dir))
