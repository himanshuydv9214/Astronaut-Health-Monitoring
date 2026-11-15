"""Personal, context-conditioned Bayesian baselines.

Why Bayesian (Normal-Inverse-Gamma conjugate model)?
* Few samples early in a mission: a population prior gives sensible
  behaviour on day 1 and is progressively replaced by the individual's data.
* The posterior predictive is a Student-t, so the deviation score carries
  its own uncertainty: a baseline learned from 30 samples produces wider
  bands than one learned from 3 days. That uncertainty feeds the
  emergency classifier's confidence.
* Exponential forgetting (half-life, default 7 days) lets the baseline
  track slow, expected spaceflight adaptation, while z-gating (samples
  with |z| > gate are not learned) stops acute events from being absorbed
  into "normal".

Why context-conditioned? A heart rate of 105 bpm is normal during
exercise and abnormal during sleep. Baselines are kept separately for
sleep / rest / exercise / post-exercise recovery, with context inferred
from the (measured) activity sensor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

from ares.config import DETECTION, PARAMS

CONTEXTS = ("sleep", "rest", "exercise", "recovery")

# Weak prior offsets by context (rough textbook direction/magnitude only;
# defined independently of the simulator and quickly overwhelmed by data).
CONTEXT_PRIOR_OFFSETS = {
    "sleep": {"hr": -10, "hrv_rmssd": 10, "rr": -2, "sbp": -10, "dbp": -7, "temp": -0.3},
    "rest": {},
    "exercise": {"hr": 50, "hrv_rmssd": -20, "rr": 10, "sbp": 25, "temp": 0.5},
    "recovery": {"hr": 25, "hrv_rmssd": -10, "rr": 5, "sbp": 12, "temp": 0.3},
}

# expected WITHIN-person variability (sd) used for the prior on sigma^2
WITHIN_SD = {"hr": 4.0, "hrv_rmssd": 8.0, "spo2": 0.8, "rr": 1.2, "sbp": 5.0, "dbp": 4.0, "temp": 0.15}


@dataclass
class NIG:
    mu: float
    kappa: float
    alpha: float
    beta: float
    n: int = 0

    def predictive(self) -> tuple[float, float, float]:
        """(loc, scale, dof) of the Student-t posterior predictive."""
        scale = math.sqrt(self.beta * (self.kappa + 1) / (self.alpha * self.kappa))
        return self.mu, scale, 2 * self.alpha

    def update(self, x: float, lam: float, prior: "NIG") -> None:
        # discount (forgetting), floored at the prior's strength
        self.kappa = max(self.kappa * lam, prior.kappa)
        a_new = max(self.alpha * lam, prior.alpha)
        self.beta *= a_new / self.alpha          # keeps the variance estimate unchanged
        self.alpha = a_new
        k1 = self.kappa + 1
        self.beta += self.kappa * (x - self.mu) ** 2 / (2 * k1)
        self.mu = (self.kappa * self.mu + x) / k1
        self.kappa = k1
        self.alpha += 0.5
        self.n += 1


def make_prior(key: str, ctx: str) -> NIG:
    spec = PARAMS[key]
    off = CONTEXT_PRIOR_OFFSETS[ctx].get(key, 0.0)
    sd = WITHIN_SD[key] * (1.6 if ctx in ("exercise", "recovery") else 1.0)
    alpha0 = 3.0
    return NIG(mu=spec.prior_mean + off, kappa=1.0, alpha=alpha0, beta=sd ** 2 * (alpha0 - 1))


class PersonalBaseline:
    def __init__(self, half_life_days: float = DETECTION.baseline_half_life_days):
        self.lam = 0.5 ** (1.0 / (half_life_days * 1440.0))
        self.priors = {(k, c): make_prior(k, c) for k in PARAMS for c in CONTEXTS}
        self.post = {kc: NIG(**vars(p)) for kc, p in self.priors.items()}
        self.premission: dict | None = None

    def score(self, key: str, ctx: str, x: float) -> dict:
        nig = self.post[(key, ctx)]
        loc, scale, dof = nig.predictive()
        z = (x - loc) / scale
        p_two = float(2 * stats.t.sf(abs(z), dof))
        return {"z": float(z), "expected": float(loc), "scale": float(scale), "dof": float(dof),
                "p": p_two, "n": nig.n, "uncertainty": float(1.0 / math.sqrt(max(nig.kappa, 1.0)))}

    def update(self, key: str, ctx: str, x: float, z: float | None = None, force: bool = False) -> bool:
        if x is None or np.isnan(x):
            return False
        nig = self.post[(key, ctx)]
        if not force and nig.n >= DETECTION.warmup_samples and z is not None and abs(z) > DETECTION.baseline_gate_z:
            return False
        nig.update(float(x), self.lam, self.priors[(key, ctx)])
        return True

    def snapshot(self) -> dict:
        return {f"{k}|{c}": {"mean": v.predictive()[0], "sd": v.predictive()[1], "n": v.n}
                for (k, c), v in self.post.items()}

    def freeze_premission(self) -> None:
        self.premission = self.snapshot()

    def drift_from_premission(self, key: str, ctx: str = "rest") -> float | None:
        if not self.premission:
            return None
        return self.post[(key, ctx)].predictive()[0] - self.premission[f"{key}|{ctx}"]["mean"]


class ContextEstimator:
    """Infers activity context from the MEASURED accelerometer counts.

    A lagged (tau = 5 min) activity estimate distinguishes 'recovery'
    (just stopped exercising, HR still elevated) from true rest, which
    removes a major source of false alarms in naive monitors.
    """

    def __init__(self, tau_min: float = 6.0):
        self.a = 1 - math.exp(-1.0 / tau_min)
        self.smooth = 0.25
        self.slow = 0.25

    def update(self, counts: float) -> str:
        self.smooth += (counts - self.smooth) * self.a
        self.slow += (counts - self.slow) * (1 - math.exp(-1.0 / 15.0))
        if counts > 0.8:
            return "exercise"
        if self.slow > 0.35:
            return "recovery"
        if counts < 0.09 and self.smooth < 0.15:
            return "sleep"
        return "rest"
