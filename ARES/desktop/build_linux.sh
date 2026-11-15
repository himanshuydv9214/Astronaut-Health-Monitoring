#!/usr/bin/env bash
# ARES - build the Linux desktop app:  dist/ARES/ARES  +  dist/ARES-0.5.0-linux-x64.tar.gz
# Needs Python 3.11+, and at run time the usual desktop libraries (X11/Wayland, libxcb-cursor0, libnss3, libgl1).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=0.5.0
[ -x .venv/bin/python ] || { python3 -m venv .venv; .venv/bin/pip install -r requirements.txt; }
.venv/bin/pip install -r desktop/requirements-desktop.txt
[ -f ares/web3d_dist/index.html ] || { echo "interface not built: cd web3d && npm ci && npm run build"; exit 1; }
[ -f desktop/assets/ares.png ] || .venv/bin/python desktop/make_icon.py
.venv/bin/python -m PyInstaller --noconfirm --clean --distpath dist --workpath build/ares desktop/ares.spec
ARES_DATA_DIR="$PWD/build/selftest-data" dist/ARES/ARES --self-test > build/selftest.json || { cat build/selftest.json; exit 1; }
echo "self-test passed"
cp desktop/assets/ares.png dist/ARES/ares.png
cat > dist/ARES/ares.desktop <<DESK
[Desktop Entry]
Type=Application
Name=ARES
Comment=Astronaut health monitoring and emergency decision support
Exec=sh -c '"\$(dirname "%k")/ARES"'
Icon=ares
Categories=Science;MedicalSoftware;
DESK
tar -C dist -czf "dist/ARES-$VERSION-linux-x64.tar.gz" ARES
echo "dist/ARES/ARES  and  dist/ARES-$VERSION-linux-x64.tar.gz"
