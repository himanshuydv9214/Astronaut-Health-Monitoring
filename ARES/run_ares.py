"""One-command launcher: starts the ARES server and opens the browser when it is ready.

    python run_ares.py
"""
import os
import sys
import threading
import time
import urllib.request
import webbrowser

os.environ.setdefault("OMP_NUM_THREADS", "1")
URL = "http://127.0.0.1:8000"


def open_when_ready():
    for _ in range(120):                      # baseline acquisition takes ~15-30 s on first start
        try:
            urllib.request.urlopen(URL + "/api/mission", timeout=2)
            print(f"\n  ARES is ready -> {URL}\n  (keep this window open; press Ctrl+C to stop)\n")
            webbrowser.open(URL)
            return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    print(f"\n  ARES did not answer yet - open {URL} manually in your browser.\n")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    print("  Starting ARES (building the crew's personal baselines, about 15-30 seconds)...")
    threading.Thread(target=open_when_ready, daemon=True).start()
    from ares.api.server import main
    main()
