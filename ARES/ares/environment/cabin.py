"""Cabin environment intelligence: CO2, O2, temperature, humidity (SIMULATED sensors).

Why this matters (from the team's closed-environment research and NASA OCHMO):
  * NASA-STD-3001 Vol 2 [V2 6004]: average 1-hour ppCO2 <= 3 mmHg.
  * Law et al. (NASA JSC): to keep headache risk < 1%, the 7-day average ppCO2
    should stay < 2.5 mmHg; crews have reported symptoms from ~2.3 mmHg.
  * [V2 6013] crew performance zone: 20-25 degC, 30-60 % relative humidity.

The key idea is ATTRIBUTION. When several crew members show the same change at
the same time (e.g., breathing faster) while ppCO2 is rising, the most likely
cause is the cabin, not an illness in each person. ARES flags this as an
environmental pattern and recommends checking CO2 removal / ventilation first,
instead of opening four separate medical incidents. Conversely, a deviation in
ONE crew member while the cabin is nominal points away from the environment.

Sensor model: well-mixed single-volume cabin, ppCO2 driven by crew metabolic
CO2 output (higher during exercise) and removal-system efficiency; local
pockets (poor microgravity convection) are NOT modelled.
"""

from __future__ import annotations

from collections import deque

import numpy as np

CO2_1H_LIMIT = 3.0        # mmHg, NASA-STD-3001 V2 6004
CO2_7D_ADVISORY = 2.5     # mmHg, headache risk < 1 % (Law et al.)
TEMP_ZONE = (20.0, 25.0)  # degC, V2 6013
RH_ZONE = (30.0, 60.0)    # %, V2 6013
NOMINAL_CO2 = 2.2         # mmHg, simulated nominal set-point (illustrative)


class CabinSimulator:
    """First-order cabin model (illustrative, not an ECLSS model)."""

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)
        self.co2 = NOMINAL_CO2
        self.temp = 22.5
        self.rh = 45.0
        self.ppo2 = 158.0

    def step(self, t: float, n_exercising: int, removal_efficiency: float = 1.0, extra_co2: float = 0.0) -> dict:
        # equilibrium rises with exercise load and falls with scrubber efficiency
        target = NOMINAL_CO2 * (1 + 0.08 * n_exercising) / max(removal_efficiency, 0.15) + extra_co2
        self.co2 += (target - self.co2) * 0.03 + self.rng.normal(0, 0.03)
        self.temp += (22.5 + 0.3 * n_exercising - self.temp) * 0.05 + self.rng.normal(0, 0.03)
        self.rh += (45 + 2 * n_exercising - self.rh) * 0.05 + self.rng.normal(0, 0.2)
        self.ppo2 += (158.0 - self.ppo2) * 0.05 + self.rng.normal(0, 0.2)
        return {"t": t, "ppco2_mmhg": round(max(self.co2, 0.1), 2), "temp_c": round(self.temp, 2),
                "rh_pct": round(self.rh, 1), "ppo2_mmhg": round(self.ppo2, 1)}


class CabinMonitor:
    def __init__(self):
        self.hist: deque = deque(maxlen=7 * 1440)

    def update(self, s: dict) -> None:
        self.hist.append(s)

    def _avg(self, minutes: int, key: str) -> float | None:
        if not self.hist:
            return None
        vals = [h[key] for h in list(self.hist)[-minutes:]]
        return float(np.mean(vals))

    def assess(self, crew_states: dict[str, dict]) -> dict:
        if not self.hist:
            return {"status": "no data"}
        cur = self.hist[-1]
        a1, a24, a7 = self._avg(60, "ppco2_mmhg"), self._avg(1440, "ppco2_mmhg"), self._avg(7 * 1440, "ppco2_mmhg")
        findings, level = [], 0
        if a1 > CO2_1H_LIMIT:
            level = max(level, 2)
            findings.append(f"1-h mean ppCO2 {a1:.2f} mmHg exceeds the NASA-STD-3001 limit of {CO2_1H_LIMIT} mmHg")
        elif a7 is not None and len(self.hist) > 1440 and a7 > CO2_7D_ADVISORY:
            level = max(level, 1)
            findings.append(f"7-day mean ppCO2 {a7:.2f} mmHg above {CO2_7D_ADVISORY} mmHg (headache-risk advisory)")
        if not (TEMP_ZONE[0] <= cur["temp_c"] <= TEMP_ZONE[1]):
            level = max(level, 1)
            findings.append(f"Cabin temperature {cur['temp_c']:.1f} degC outside the 20-25 degC performance zone")
        if not (RH_ZONE[0] <= cur["rh_pct"] <= RH_ZONE[1]):
            level = max(level, 1)
            findings.append(f"Relative humidity {cur['rh_pct']:.0f}% outside 30-60%")

        # crew-wide co-deviation -> environmental attribution
        resp_up = [aid for aid, st in crew_states.items()
                   if st and (st["z"].get("rr") or 0) >= 2.0 and st["quality"]["rr"] >= 0.6]
        attribution = None
        n = len(crew_states)
        if len(resp_up) >= max(2, n // 2) and a1 > CO2_7D_ADVISORY:
            attribution = {"cause": "environmental (cabin CO2) likely",
                           "crew": resp_up,
                           "text": f"{len(resp_up)}/{n} crew breathing faster than their own baseline at the same time "
                                   f"while ppCO2 = {a1:.2f} mmHg - check CO2 removal / ventilation before treating "
                                   "this as individual illness."}
            level = max(level, 2)
        elif len(resp_up) == 1 and a1 <= CO2_7D_ADVISORY:
            attribution = {"cause": "individual (cabin nominal)", "crew": resp_up,
                           "text": "Only one crew member affected and the cabin is nominal - environmental cause unlikely."}
        return {"current": cur, "co2_1h": round(a1, 2), "co2_24h": round(a24, 2), "co2_7d": round(a7, 2),
                "level": level, "findings": findings, "attribution": attribution,
                "limits": {"co2_1h_mmhg": CO2_1H_LIMIT, "co2_7d_advisory_mmhg": CO2_7D_ADVISORY,
                           "temp_c": TEMP_ZONE, "rh_pct": RH_ZONE},
                "source": "NASA-STD-3001 Vol 2 [V2 6004, V2 6013]; OCHMO-TB-004 (CO2). Sensors SIMULATED."}

    def series(self, n: int = 240) -> dict:
        h = list(self.hist)[-n:]
        return {"t": [x["t"] for x in h], "ppco2": [x["ppco2_mmhg"] for x in h], "temp": [x["temp_c"] for x in h],
                "rh": [x["rh_pct"] for x in h]}
