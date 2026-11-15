#!/usr/bin/env bash
# macOS / Linux launcher: ./start_ares.sh
cd "$(dirname "$0")"
if [ ! -f .ares_installed ]; then
  echo "First start: installing required packages..."
  python3 -m pip install -r requirements.txt && touch .ares_installed || exit 1
fi
python3 run_ares.py
