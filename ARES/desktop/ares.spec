# PyInstaller spec for the ARES desktop application (one-folder build).
#   Windows:  desktop\build_windows.bat      ->  dist\ARES\ARES.exe  (+ installer via Inno Setup)
#   Linux:    desktop/build_linux.sh         ->  dist/ARES/ARES
# The build folder contains Python, every library, the AI models, the knowledge base, the 3D anatomy model and the
# built interface - nothing is downloaded at run time and the target computer needs no Python or Node.js.
import importlib.util
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent          # repository root (this file lives in <root>/desktop)
WIN = sys.platform == "win32"


def tree(rel, dest=None):
    """Add a folder of the repository, preserving its relative path inside the bundle."""
    src = ROOT / rel
    if not src.exists():
        raise SystemExit(f"missing required resource: {src} (build the interface / train the models first)")
    return (str(src), dest or rel)


datas = [
    tree("ares/web3d_dist"),                    # React 3D interface (built by `npm run build` in web3d/)
    tree("ares/web"),                           # classic dashboard + /static
    tree("assets/anatomy"),                     # BodyParts3D GLB + region map
    tree("knowledge_base"),                     # medical guidance / protocols
    tree("models"),                             # trained scikit-learn models + model card
    tree("reports"),                            # real-data validation results shown in Data & System
    tree("data/osdr"),                          # NASA OSDR source files (read-only provenance)
    tree("data/external"),                      # RadLab / SRAG / DONKI source files (read-only)
    tree("data/cache"),                         # bundled space-weather cache
    (str(ROOT / "desktop/splash.html"), "desktop"),
    (str(ROOT / "desktop/about.html"), "desktop"),
    (str(ROOT / "desktop/already_running.html"), "desktop"),
    (str(ROOT / "desktop/assets"), "desktop/assets"),
]
datas += collect_data_files("plotly", includes=["package_data/plotly.min.js"])   # served locally at /vendor/plotly.min.js
datas += collect_data_files("webview")

hiddenimports = (collect_submodules("ares") + collect_submodules("uvicorn") + collect_submodules("websockets")
                 + ["sklearn.ensemble", "sklearn.isotonic", "sklearn.tree", "sklearn.utils._typedefs",
                    "sklearn.neighbors._partition_nodes", "scipy.special.cython_special", "webview.platforms.edgechromium"
                    if WIN else "webview.platforms.qt"])
if importlib.util.find_spec("shap"):            # optional: per-prediction explanations
    hiddenimports.append("shap")

# Not used at run time (training / reports / optional imports of shap & pandas) - keeps the build small.
excludes = ["IPython", "jupyter", "notebook", "pytest", "wfdb", "torch", "tensorflow", "tkinter",
            "PyQt5", "PySide2", "PySide6", "cv2", "skimage", "pyarrow", "lxml", "aiohttp", "cryptography",
            "numba.cuda", "dask", "distributed", "sphinx", "black", "pygments", "PyQt6.QtQuick3D", "PyQt6.QtMultimedia",
            "PyQt6.QtBluetooth", "PyQt6.QtSensors", "PyQt6.QtSerialPort", "PyQt6.QtPdf", "PyQt6.QtDesigner"] + (["PyQt6", "qtpy"] if WIN else [])

a = Analysis([str(ROOT / "desktop/ares_desktop.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hiddenimports,
             excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ARES", console=False, debug=False, upx=False,
          icon=str(ROOT / "desktop/assets/ares.ico"), version=str(ROOT / "desktop/version_info.txt") if WIN else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ARES")
