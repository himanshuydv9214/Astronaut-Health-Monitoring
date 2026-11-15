"""Synthetic behavioral data for the fictional crew (ALL SIMULATED).

Illustrative dose-response, qualitatively following the sleep-restriction
literature (Van Dongen et al., SLEEP 2003: PVT lapses rise roughly linearly
with cumulative sleep debt; Basner 2011: response speed is the most sensitive
PVT-B metric). Magnitudes are NOT fitted to data.
"""

from __future__ import annotations

import numpy as np

from ares.behavioral.pvt import ISI_RANGE_S, DURATION_S, score_pvt


def simulate_pvt(rng: np.random.Generator, base_rt_ms: float, debt_h: float, strain: float) -> dict:
    """Generate one 3-min PVT-B as raw RTs and score it."""
    n_trials = int(DURATION_S / np.mean(ISI_RANGE_S))
    impair = 0.9 * debt_h + 8.0 * strain           # illustrative
    rt = rng.lognormal(np.log(base_rt_ms + 4.0 * impair), 0.13, n_trials)
    p_lapse = min(0.6, 0.01 + 0.012 * impair)
    lapses = rng.random(n_trials) < p_lapse
    rt[lapses] = rng.uniform(355, 900, lapses.sum())
    anticip = int(rng.poisson(0.3 + 0.05 * impair))
    return score_pvt(rt.tolist(), anticip)


def simulate_checkin(rng: np.random.Generator, last_sleep_h: float, need_h: float, debt_h: float,
                     strain: float) -> dict:
    deficit = max(0.0, need_h - last_sleep_h)
    sp = int(np.clip(round(2 + 0.55 * deficit + 0.12 * debt_h + 2.5 * strain + rng.normal(0, 0.6)), 1, 7))

    def vas(mu):
        return float(np.clip(round(mu + rng.normal(0, 0.8)), 0, 10))
    return {"samn_perelli": sp, "mood": vas(7.2 - 3.5 * strain - 0.15 * debt_h),
            "stress": vas(3.0 + 4.5 * strain + 0.1 * debt_h), "workload": vas(5 + 2.5 * strain),
            "sleep_quality": vas(7.0 - 0.8 * deficit - 2.0 * strain)}
