"""Fetch the REAL open datasets ARES uses (run this with internet access).

    python scripts/fetch_data.py            # everything
    python scripts/fetch_data.py --donki    # only NASA DONKI SEP events

Downloads
  1. NASA DONKI Solar Energetic Particle (SEP) events (last 365 days)
       https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/SEP   (no key)
       https://api.nasa.gov/DONKI/SEP                       (NASA_API_KEY or DEMO_KEY)
     -> data/cache/donki_sep.json  (shown in the dashboard radiation panel)
  2. PhysioNet MIT-BIH Arrhythmia Database - all 48 records (ODC-By 1.0)
       https://physionet.org/files/mitdb/1.0.0/
     -> data/external/mitdb/   (validate_real_data.py uses record 100 by default)
  3. PhysioNet drivedb record drive02 (ODC-By 1.0) via the WFDB sample set
     -> data/external/wfdb_samples/

The build environment for this prototype could only reach GitHub, so the
committed validation used the MIT-BIH and drivedb records mirrored in the
MIT-LCP/wfdb-python sample-data folder; this script fetches the full sets.
"""
import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXT = ROOT / "data" / "external"
MITDB = ["100", "101", "102", "103", "104", "105", "106", "107", "108", "109", "111", "112", "113", "114", "115",
         "116", "117", "118", "119", "121", "122", "123", "124", "200", "201", "202", "203", "205", "207", "208",
         "209", "210", "212", "213", "214", "215", "217", "219", "220", "221", "222", "223", "228", "230", "231",
         "232", "233", "234"]
WFDB_SAMPLE = "https://raw.githubusercontent.com/MIT-LCP/wfdb-python/main/sample-data/"


def get(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            dest.write_bytes(r.read())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ! {url}: {e}")
        return False


def donki():
    from ares.radiation.donki import fetch_sep

    try:
        ev = fetch_sep()
        print(f"DONKI: {len(ev)} SEP events cached")
    except ConnectionError as e:
        print(f"DONKI unreachable ({e}); dashboard will show the empty cache")


def mitdb(all_records: bool):
    recs = MITDB if all_records else ["100"]
    ok = 0
    for r in recs:
        good = all(get(f"https://physionet.org/files/mitdb/1.0.0/{r}.{e}", EXT / "mitdb" / f"{r}.{e}") or
                   get(f"{WFDB_SAMPLE}{r}.{e}", EXT / "mitdb" / f"{r}.{e}") for e in ("hea", "dat", "atr"))
        ok += good
    print(f"MIT-BIH: {ok}/{len(recs)} records")


def drivedb():
    ok = all(get(f"{WFDB_SAMPLE}drive02.{e}", EXT / "wfdb_samples" / f"drive02.{e}") for e in ("hea", "dat"))
    print(f"drivedb drive02: {'ok' if ok else 'failed'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--donki", action="store_true")
    ap.add_argument("--all-mitdb", action="store_true", help="all 48 MIT-BIH records (~100 MB)")
    a = ap.parse_args()
    donki()
    if not a.donki:
        mitdb(a.all_mitdb)
        drivedb()
