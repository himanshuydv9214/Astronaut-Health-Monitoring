"""ECG processing: filtering, R-peak detection, HR/HRV, signal quality.

Design choices and justification
--------------------------------
* Band-pass 0.5-40 Hz, 2nd-order Butterworth, zero-phase (filtfilt):
  0.5 Hz removes respiratory baseline wander; 40 Hz removes EMG and
  powerline while keeping QRS energy (5-25 Hz). This is the conventional
  "monitoring mode" ECG band. Zero-phase avoids shifting R-peak timing.
* R-peak detection: simplified Pan & Tompkins (IEEE TBME 1985): band-pass
  5-15 Hz -> derivative -> squaring -> 150 ms moving-window integration ->
  adaptive threshold, 250 ms refractory period, then refine to the local
  maximum of the filtered ECG.
* HRV: time-domain RMSSD/SDNN are reported for short windows. Frequency
  domain (LF/HF) is only computed for windows >= 120 s, following the
  Task Force of ESC/NASPE (Circulation 1996) recommendation that spectral
  HRV needs ~2-5 min recordings. Short windows return None, not a number.
* Signal-quality index combines beat-template correlation, kurtosis
  (clean ECG is highly peaked; Li & Clifford-style kSQI) and RR
  physiological plausibility.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sps
from scipy.stats import kurtosis


def bandpass(x: np.ndarray, fs: float, lo: float = 0.5, hi: float = 40.0, order: int = 2) -> np.ndarray:
    nyq = fs / 2.0
    hi = min(hi, nyq * 0.95)
    b, a = sps.butter(order, [lo / nyq, hi / nyq], btype="band")
    return sps.filtfilt(b, a, x)


def detect_r_peaks(ecg: np.ndarray, fs: float) -> np.ndarray:
    """Return R-peak sample indices."""
    if len(ecg) < fs:  # < 1 s of data
        return np.array([], dtype=int)
    filt = bandpass(ecg, fs, 0.5, 40.0)
    qrs = bandpass(ecg, fs, 5.0, 15.0)
    deriv = np.gradient(qrs)
    sq = deriv ** 2
    win = max(1, int(0.150 * fs))
    integ = np.convolve(sq, np.ones(win) / win, mode="same")
    refractory = int(0.25 * fs)
    thr = 0.35 * np.percentile(integ, 98)
    cand, _ = sps.find_peaks(integ, height=thr, distance=refractory)
    peaks = []
    half = int(0.08 * fs)
    for c in cand:
        lo, hi = max(0, c - half), min(len(filt), c + half)
        seg = filt[lo:hi]
        # R wave assumed positive in this lead
        peaks.append(lo + int(np.argmax(seg)))
    peaks = np.unique(np.array(peaks, dtype=int))
    # enforce refractory after refinement
    if len(peaks) > 1:
        keep = [peaks[0]]
        for p in peaks[1:]:
            if p - keep[-1] >= refractory:
                keep.append(p)
        peaks = np.array(keep)
    return peaks


@dataclass
class HRVResult:
    hr_bpm: float | None
    rmssd_ms: float | None
    sdnn_ms: float | None
    pnn50: float | None
    lf_hf: float | None
    n_beats: int
    rr_ms: np.ndarray


def hrv_from_peaks(peaks: np.ndarray, fs: float, window_s: float) -> HRVResult:
    if len(peaks) < 3:
        return HRVResult(None, None, None, None, None, len(peaks), np.array([]))
    rr = np.diff(peaks) / fs * 1000.0
    rr_valid = rr[(rr > 270) & (rr < 2200)]  # 27-222 bpm physiological window
    if len(rr_valid) < 2:
        return HRVResult(None, None, None, None, None, len(peaks), rr)
    hr = 60000.0 / float(np.median(rr_valid))
    d = np.diff(rr_valid)
    rmssd = float(np.sqrt(np.mean(d ** 2))) if len(d) else None
    sdnn = float(np.std(rr_valid, ddof=1)) if len(rr_valid) > 2 else None
    pnn50 = float(np.mean(np.abs(d) > 50) * 100) if len(d) else None
    lf_hf = None
    if window_s >= 120 and len(rr_valid) > 60:
        lf_hf = _lf_hf(rr_valid)
    return HRVResult(hr, rmssd, sdnn, pnn50, lf_hf, len(peaks), rr_valid)


def _lf_hf(rr_ms: np.ndarray, fs_interp: float = 4.0) -> float | None:
    t = np.cumsum(rr_ms) / 1000.0
    t -= t[0]
    if t[-1] < 60:
        return None
    ti = np.arange(0, t[-1], 1 / fs_interp)
    rri = np.interp(ti, t, rr_ms)
    f, pxx = sps.welch(rri - rri.mean(), fs=fs_interp, nperseg=min(256, len(rri)))
    lf = np.trapezoid(pxx[(f >= 0.04) & (f < 0.15)], f[(f >= 0.04) & (f < 0.15)])
    hf = np.trapezoid(pxx[(f >= 0.15) & (f < 0.40)], f[(f >= 0.15) & (f < 0.40)])
    return float(lf / hf) if hf > 0 else None


def ecg_quality(ecg: np.ndarray, peaks: np.ndarray, fs: float) -> float:
    """Signal quality index in [0,1]."""
    if len(peaks) < 3:
        return 0.0
    filt = bandpass(ecg, fs)
    half = int(0.2 * fs)
    beats = [filt[p - half:p + half] for p in peaks if p - half >= 0 and p + half <= len(filt)]
    if len(beats) < 2:
        return 0.1
    beats = np.array(beats)
    template = beats.mean(axis=0)
    corr = np.mean([np.corrcoef(b, template)[0, 1] for b in beats])
    corr_score = float(np.clip((corr - 0.5) / 0.45, 0, 1))
    k = kurtosis(filt, fisher=False)
    k_score = float(np.clip((k - 3.0) / 5.0, 0, 1))
    rr = np.diff(peaks) / fs
    plaus = float(np.mean((rr > 0.27) & (rr < 2.2)))
    return float(np.clip(0.5 * corr_score + 0.25 * k_score + 0.25 * plaus, 0, 1))


def process_ecg_window(ecg: np.ndarray, fs: float) -> dict:
    peaks = detect_r_peaks(ecg, fs)
    res = hrv_from_peaks(peaks, fs, len(ecg) / fs)
    q = ecg_quality(ecg, peaks, fs)
    return {
        "hr": res.hr_bpm, "hrv_rmssd": res.rmssd_ms, "sdnn": res.sdnn_ms, "pnn50": res.pnn50,
        "lf_hf": res.lf_hf, "n_beats": res.n_beats, "quality": q, "peaks": peaks,
        "rr_cv": float(np.std(res.rr_ms) / np.mean(res.rr_ms)) if len(res.rr_ms) > 2 else None,
    }
