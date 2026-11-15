# Anatomy asset attribution

`ares_body.glb` is derived from **BodyParts3D**, © The Database Center for Life Science (DBCLS),
licensed under **Creative Commons Attribution 4.0 International (CC BY 4.0)**
(licence updated by DBCLS on 2025-02-27; earlier releases were CC BY-SA 2.1 JP).

Source meshes: BodyParts3D STL files (mirror: github.com/Kevin-Mattheus-Moerman/BodyParts3D).
Reference: Mitsuhashi N, et al. *BodyParts3D: 3D structure database for anatomical concepts.*
Nucleic Acids Research 37 (2009) D782–D785.

Changes made by the ARES team (`build_glb.py`):
* 467 BodyParts3D parts grouped into 46 functional regions (`regions_manifest.json`, mapping by FMA id in `regions.json`);
* meshes merged per region and simplified (quadric decimation) for real-time display — **not for clinical or anatomical measurement**;
* coordinates converted from millimetres / Z-up to metres / Y-up, feet at y = 0.

Rebuild: `python assets/anatomy/build_glb.py --fetch`
