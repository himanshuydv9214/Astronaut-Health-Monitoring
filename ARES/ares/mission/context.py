"""Mission-context engine: where are we, how far is Earth, can we talk?

Trajectory: a Hohmann transfer between circular, coplanar orbits
(Earth 1.000 AU, Mars 1.524 AU). This is a first-order approximation
(real trajectories are Lambert solutions on eccentric, inclined orbits),
but it gives physically correct-magnitude distances and light-time delays
(~0 at departure, ~10-20 min one-way later in the mission).

Communication modes (engineering choice):
  connected : one-way light time <= 10 s (conversational links possible)
  delay     : link up, OWLT > 10 s (store-and-forward)
  blackout  : no link (solar conjunction: Sun-Earth-probe angle < 2 deg,
              or forced by scenario / operator)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ares.config import (AU_KM, EARTH_ORBIT_AU, GCR_CRUISE_MSV_PER_DAY, GCR_MARS_SURFACE_MSV_PER_DAY,
                         MARS_ORBIT_AU, SPEED_OF_LIGHT_KM_S, SUN_GM_KM3_S2)

DAY_S = 86400.0
EARTH_PERIOD_D = 365.256
MARS_PERIOD_D = 686.980
CONJUNCTION_DEG = 2.0
CONNECTED_MAX_S = 10.0


def _kepler_E(M: float, e: float) -> float:
    E = M if e < 0.8 else math.pi
    for _ in range(50):
        d = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= d
        if abs(d) < 1e-12:
            break
    return E


@dataclass
class HohmannMission:
    r1_au: float = EARTH_ORBIT_AU
    r2_au: float = MARS_ORBIT_AU
    stay_days: float = 500.0

    def __post_init__(self):
        r1, r2 = self.r1_au * AU_KM, self.r2_au * AU_KM
        self.a = (r1 + r2) / 2
        self.e = (r2 - r1) / (r2 + r1)
        self.tof_days = math.pi * math.sqrt(self.a ** 3 / SUN_GM_KM3_S2) / DAY_S
        self.nE = 2 * math.pi / EARTH_PERIOD_D
        self.nM = 2 * math.pi / MARS_PERIOD_D
        self.mars0 = math.pi - self.nM * self.tof_days   # Mars phase at departure

    def positions(self, day: float) -> tuple[tuple[float, float], tuple[float, float]]:
        """(spacecraft_xy_km, earth_xy_km) in a heliocentric frame."""
        th_e = self.nE * day
        earth = (self.r1_au * AU_KM * math.cos(th_e), self.r1_au * AU_KM * math.sin(th_e))
        if day <= self.tof_days:
            M = math.pi * day / self.tof_days
            E = _kepler_E(M, self.e)
            nu = 2 * math.atan2(math.sqrt(1 + self.e) * math.sin(E / 2), math.sqrt(1 - self.e) * math.cos(E / 2))
            r = self.a * (1 - self.e * math.cos(E))
            sc = (r * math.cos(nu), r * math.sin(nu))
        else:
            th_m = self.mars0 + self.nM * day
            sc = (self.r2_au * AU_KM * math.cos(th_m), self.r2_au * AU_KM * math.sin(th_m))
        return sc, earth

    def geometry(self, day: float) -> dict:
        sc, earth = self.positions(day)
        dx, dy = sc[0] - earth[0], sc[1] - earth[1]
        dist = math.hypot(dx, dy)
        # Sun-Earth-probe angle (elongation seen from Earth)
        sx, sy = -earth[0], -earth[1]
        cosang = (dx * sx + dy * sy) / (max(dist, 1e-9) * math.hypot(sx, sy))
        sep = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
        return {"distance_km": dist, "distance_au": dist / AU_KM, "owlt_s": dist / SPEED_OF_LIGHT_KM_S,
                "sun_earth_probe_deg": sep, "sc_xy_au": (sc[0] / AU_KM, sc[1] / AU_KM),
                "earth_xy_au": (earth[0] / AU_KM, earth[1] / AU_KM)}

    def phase(self, day: float) -> str:
        if day < 2:
            return "Earth departure"
        if day < self.tof_days - 7:
            return "Outbound cruise"
        if day < self.tof_days:
            return "Mars approach"
        if day < self.tof_days + self.stay_days:
            return "Mars surface stay"
        return "Return (not modelled)"

    def base_dose_rate(self, day: float) -> tuple[float, str]:
        if day < self.tof_days:
            return GCR_CRUISE_MSV_PER_DAY, "MSL/RAD cruise mean (Zeitlin et al., Science 2013)"
        return GCR_MARS_SURFACE_MSV_PER_DAY, "MSL/RAD Mars surface mean (Hassler et al., Science 2014)"


class MissionContext:
    def __init__(self, start_day: float = 120.0, crew_size: int = 4):
        self.traj = HohmannMission()
        self.start_day = start_day
        self.forced_blackout = False
        self.operator_mode: str | None = None
        self.crew_size = crew_size

    def status(self, t_min: float) -> dict:
        day = self.start_day + t_min / 1440.0
        g = self.traj.geometry(day)
        mode = "connected" if g["owlt_s"] <= CONNECTED_MAX_S else "delay"
        reason = ""
        if g["sun_earth_probe_deg"] < CONJUNCTION_DEG and g["distance_au"] > 1.0:
            mode, reason = "blackout", "solar conjunction"
        if self.forced_blackout:
            mode, reason = "blackout", "scenario-forced blackout"
        if self.operator_mode:
            mode, reason = self.operator_mode, "operator override"
        rate, rate_src = self.traj.base_dose_rate(day)
        return {
            "mission_day": day, "met_min": t_min, "phase": self.traj.phase(day),
            "transfer_days": self.traj.tof_days, "days_to_mars": max(0.0, self.traj.tof_days - day),
            "distance_km": g["distance_km"], "distance_au": g["distance_au"],
            "one_way_light_time_min": g["owlt_s"] / 60.0, "round_trip_min": 2 * g["owlt_s"] / 60.0,
            "sun_earth_probe_deg": g["sun_earth_probe_deg"], "comm_mode": mode, "comm_reason": reason,
            "sc_xy_au": g["sc_xy_au"], "earth_xy_au": g["earth_xy_au"],
            "gcr_model_rate_msv_day": rate, "gcr_model_source": rate_src,
            "trajectory_note": "Hohmann transfer, circular coplanar orbits (first-order approximation)",
        }
