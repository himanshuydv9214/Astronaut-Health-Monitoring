"""Local linear-trend Kalman filter (state-space model) for deviation series.

State x = [level, slope]; level is the deviation from the personal
baseline (native units), slope is its rate of change per minute.

    x_t = F x_{t-1} + w,   F = [[1, 1], [0, 1]],  w ~ N(0, Q)
    y_t = level_t + v,      v ~ N(0, R)

R comes from the baseline's predictive variance, so noisier signals
produce more cautious slope estimates. Missing observations are handled
natively (predict-only step), which matters for intermittent BP cuffs and
sensor dropouts. Output slope is reported per hour with its 1-sigma.
"""

from __future__ import annotations

import numpy as np


class LocalLinearTrend:
    def __init__(self, q_level: float = 0.02, q_slope: float = 1e-5):
        self.x = np.zeros(2)
        self.P = np.diag([1.0, 0.01])
        self.F = np.array([[1.0, 1.0], [0.0, 1.0]])
        self.qlv, self.qsl = q_level, q_slope
        self.initialised = False

    def step(self, y: float | None, r_var: float) -> tuple[float, float, float]:
        q = np.diag([self.qlv * r_var, self.qsl * r_var])
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + q
        if y is not None and not np.isnan(y):
            if not self.initialised:
                self.x = np.array([y, 0.0])
                self.P = np.diag([r_var, 0.01 * r_var])
                self.initialised = True
            else:
                h = np.array([1.0, 0.0])
                s = h @ self.P @ h + r_var
                k = self.P @ h / s
                self.x = self.x + k * (y - h @ self.x)
                self.P = (np.eye(2) - np.outer(k, h)) @ self.P
        slope_h = float(self.x[1] * 60.0)
        slope_sd_h = float(np.sqrt(max(self.P[1, 1], 0)) * 60.0)
        return float(self.x[0]), slope_h, slope_sd_h
