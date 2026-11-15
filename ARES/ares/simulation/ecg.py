"""Synthetic single-lead ECG generator (SIMULATED data).

A simplified sum-of-Gaussians beat model in the spirit of ECGSYN
(McSharry et al., IEEE TBME 2003). It is good enough to exercise the
signal-processing chain (filtering, R-peak detection, HRV, quality
assessment); it does not reproduce clinical morphology faithfully.
"""

from __future__ import annotations

import numpy as np

# (relative time within beat as fraction of RR, width in s, amplitude in mV)
_WAVES = [
    (-0.20, 0.025, 0.12),   # P
    (-0.025, 0.010, -0.12),  # Q
    (0.0, 0.010, 1.10),     # R
    (0.028, 0.012, -0.22),  # S
    (0.30, 0.060, 0.30),    # T
]


def rr_series(hr_bpm: float, rmssd_ms: float, n: int, irregular: float, rng: np.random.Generator) -> np.ndarray:
    """R-R intervals (s). iid jitter of sd s gives RMSSD ~ s*sqrt(2)."""
    mean_rr = 60.0 / max(hr_bpm, 20.0)
    s = (rmssd_ms / 1000.0) / np.sqrt(2.0)
    rr = mean_rr + rng.normal(0.0, s, n)
    if irregular > 0:
        rr += rng.uniform(-1, 1, n) * irregular * 0.28 * mean_rr
    return np.clip(rr, 0.27, 2.2)


def synth_ecg(hr_bpm: float, rmssd_ms: float, seconds: float = 10.0, fs: int = 250,
              irregular: float = 0.0, leadoff: bool = False, motion: float = 0.0,
              rng: np.random.Generator | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return (signal_mV, true_r_peak_times_s)."""
    rng = rng or np.random.default_rng()
    n = int(seconds * fs)
    t = np.arange(n) / fs
    nbeats = int(seconds * hr_bpm / 60.0) + 4
    rr = rr_series(hr_bpm, rmssd_ms, nbeats, irregular, rng)
    r_times = np.cumsum(rr) - rr[0] * rng.uniform(0.2, 0.9)
    r_times = r_times[(r_times > -0.5) & (r_times < seconds + 0.5)]
    sig = np.zeros(n)
    for k, rt in enumerate(r_times):
        rr_k = rr[min(k, len(rr) - 1)]
        for frac, width, amp in _WAVES:
            # P absent during irregular (AF-like) rhythm
            if irregular > 0.5 and frac == -0.20:
                continue
            centre = rt + frac * rr_k if frac not in (-0.025, 0.028) else rt + frac
            sig += amp * np.exp(-0.5 * ((t - centre) / width) ** 2)
    if irregular > 0.5:  # fibrillatory baseline
        sig += 0.04 * np.sin(2 * np.pi * rng.uniform(5, 7) * t + rng.uniform(0, 6.28))
    # realistic contaminants
    sig += 0.15 * np.sin(2 * np.pi * 0.25 * t + rng.uniform(0, 6.28))   # baseline wander
    sig += 0.02 * np.sin(2 * np.pi * 50.0 * t)                          # powerline
    sig += rng.normal(0, 0.02, n)                                       # sensor noise
    if motion > 0:
        sig += motion * np.cumsum(rng.normal(0, 0.05, n)) / np.sqrt(fs) * 3
        sig += rng.normal(0, 0.15 * motion, n)
    if leadoff:
        sig = rng.normal(0, 0.8, n) + 1.5 * np.sign(np.sin(2 * np.pi * 0.7 * t))
    true_r = r_times[(r_times >= 0) & (r_times < seconds)]
    return sig, true_r
