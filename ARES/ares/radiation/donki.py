"""NASA DONKI (Space Weather Database Of Notifications, Knowledge, Information) client.

Fetches REAL Solar Energetic Particle (SEP) event records. Used to show
actual recent SEP activity and to replay real event timing in the
radiation scenario. DONKI records event occurrence/instruments, not dose at
a Mars-bound vehicle, so ARES never converts DONKI records into crew dose.

Endpoints (public):
  https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/SEP?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
  https://api.nasa.gov/DONKI/SEP?startDate=...&endDate=...&api_key=DEMO_KEY
Offline-first: results are cached in data/cache/donki_sep.json.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from ares.paths import APP_ROOT, DATA_DIR  # noqa: E402

CACHE = DATA_DIR / "cache" / "donki_sep.json"
BUNDLED_CACHE = APP_ROOT / "data" / "cache" / "donki_sep.json"   # read-only copy shipped with the app
URLS = [
    "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/SEP?startDate={s}&endDate={e}",
    "https://api.nasa.gov/DONKI/SEP?startDate={s}&endDate={e}&api_key={k}",
]


def fetch_sep(start: str | None = None, end: str | None = None, timeout: float = 15.0) -> list[dict]:
    end = end or date.today().isoformat()
    start = start or (date.fromisoformat(end) - timedelta(days=365)).isoformat()
    key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
    last_err = None
    for u in URLS:
        url = u.format(s=start, e=end, k=key)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data = json.loads(r.read().decode() or "[]")
            records = parse(data)
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps({"source": url.split("?")[0], "start": start, "end": end,
                                         "fetched": date.today().isoformat(), "events": records}, indent=1))
            return records
        except Exception as ex:  # network unavailable is a normal, expected condition on board
            last_err = ex
    raise ConnectionError(f"DONKI unreachable: {last_err}")


def parse(data: list) -> list[dict]:
    out = []
    for ev in data or []:
        out.append({
            "sepID": ev.get("sepID"), "eventTime": ev.get("eventTime"),
            "instruments": [i.get("displayName") for i in ev.get("instruments") or []],
            "linkedEvents": [l.get("activityID") for l in ev.get("linkedEvents") or []],
            "link": ev.get("link"),
        })
    return out


def load_cached() -> dict | None:
    for f in (CACHE, BUNDLED_CACHE):
        if not f.exists():
            continue
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
    return None
