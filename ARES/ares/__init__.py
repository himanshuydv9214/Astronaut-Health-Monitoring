"""ARES - Autonomous Risk Evaluation & Emergency Support.

Research prototype for onboard astronaut health decision support.
NOT a medical device. Not clinically validated. See docs/LIMITATIONS.md.
"""

import os as _os

# Single-threaded numerical inference. Onboard computers are small, and OpenMP thread
# spinning on single-row predictions made the forecaster ~100x slower (700 ms -> 6 ms).
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_v, "1")

__version__ = "0.5.0"
