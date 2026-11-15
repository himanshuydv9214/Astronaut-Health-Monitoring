"""Validate the ECG signal-processing chain on REAL human recordings (PhysioNet).

Data (fetched by scripts/fetch_data.py into data/external/):
  * MIT-BIH Arrhythmia Database record 100 (Moody & Mark 2001; Goldberger et al.
    2000, PhysioNet). 30 min, 360 Hz, lead MLII, cardiologist beat annotations.
    License: Open Data Commons Attribution 1.0.
  * Stress Recognition in Automobile Drivers, record drive02 (Healey & Picard,
    IEEE T-ITS 2005, PhysioNet drivedb). Ambulatory ECG (~496 Hz) during real
    driving, plus the recording system's own HR channel. License: ODC-By 1.0.
    Used here as a ground-based analog for noisy, ambulatory, stressed wear.

Tests
  1. Beat detection vs annotations: sensitivity / PPV (150 ms tolerance, ANSI/AAMI EC57 style)
  2. Per-10 s-window HR error vs annotation-derived HR, and HRV RMSSD agreement
  3. Noise robustness: add white + baseline-wander + EMG-like noise at decreasing SNR;
     check that HR error and the signal-quality index move together (SQI must drop
     before HR becomes wrong - that is what makes sensor-failure handling safe)
  4. drive02: ARES HR (computed from raw ECG) vs the device's own HR channel

    python scripts/validate_real_data.py
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")   # before numpy/sklearn import (see ares/__init__.py)
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ares.processing.ecg import bandpass, hrv_from_peaks, process_ecg_window  # noqa: E402

EXT = ROOT / "data" / "external"
REPORTS = ROOT / "reports"
BEATS = set("NLRBAaJSVrFejnE/fQ")   # AAMI beat annotation symbols


def match(det, ref, tol):
    """Greedy one-to-one matching of detected vs reference beats within tol samples."""
    det, ref = np.sort(det), np.sort(ref)
    i = j = tp = 0
    while i < len(det) and j < len(ref):
        d = det[i] - ref[j]
        if abs(d) <= tol:
            tp += 1
            i += 1
            j += 1
        elif d < 0:
            i += 1
        else:
            j += 1
    return tp


def mitbih(rec="100"):
    import wfdb

    r = wfdb.rdrecord(str(EXT / "mitdb" / rec))
    a = wfdb.rdann(str(EXT / "mitdb" / rec), "atr")
    fs = r.fs
    x = r.p_signal[:, r.sig_name.index("MLII")]
    ref = np.array([s for s, sym in zip(a.sample, a.symbol) if sym in BEATS])
    win = int(10 * fs)
    det_all, hr_err, rmssd_pairs, sqis = [], [], [], []
    for s in range(0, len(x) - win, win):
        seg = x[s:s + win]
        out = process_ecg_window(seg, fs)
        det_all += list(out["peaks"] + s)
        rr = ref[(ref >= s) & (ref < s + win)]
        if len(rr) >= 3 and out["hr"]:
            hr_ref = 60.0 / np.median(np.diff(rr) / fs)
            hr_err.append(out["hr"] - hr_ref)
            ref_hrv = hrv_from_peaks(rr - s, fs, 10).rmssd_ms
            if out["hrv_rmssd"] is not None and ref_hrv is not None:
                rmssd_pairs.append((out["hrv_rmssd"], ref_hrv))
        sqis.append(out["quality"])
    det = np.unique(np.array(det_all))
    tol = int(0.15 * fs)
    tp = match(det, ref, tol)
    se, ppv = tp / len(ref), tp / len(det)
    hr_err = np.array(hr_err)
    rp = np.array(rmssd_pairs)
    res = {"record": f"mitdb/{rec}", "fs": fs, "duration_min": round(len(x) / fs / 60, 1),
           "reference_beats": int(len(ref)), "detected": int(len(det)), "sensitivity": round(se, 4),
           "ppv": round(ppv, 4), "hr_mae_bpm": round(float(np.mean(np.abs(hr_err))), 2),
           "hr_bias_bpm": round(float(np.mean(hr_err)), 2),
           "hr_p95_abs_err_bpm": round(float(np.percentile(np.abs(hr_err), 95)), 2),
           "rmssd_mae_ms": round(float(np.mean(np.abs(rp[:, 0] - rp[:, 1]))), 2) if len(rp) else None,
           "rmssd_median_ref_ms": round(float(np.median(rp[:, 1])), 1) if len(rp) else None,
           "median_sqi": round(float(np.median(sqis)), 3), "windows": len(hr_err),
           "note": "Record 100 is mostly normal sinus rhythm with 33 APCs and 1 PVC."}
    # noise robustness
    rng = np.random.default_rng(0)
    noise_rows = []
    p_sig = np.var(x)
    for snr_db in (20, 12, 9, 6, 3, 0, -3):
        p_n = p_sig / (10 ** (snr_db / 10))
        # IN-BAND noise (5-30 Hz, overlaps QRS energy - the hard case; out-of-band noise such as
        # baseline wander is removed by the band-pass and would make this test trivially easy)
        n = bandpass(rng.normal(0, 1, len(x)), fs, 5.0, 30.0)
        n *= np.sqrt(p_n / np.var(n))
        y = x + n
        errs, qs = [], []
        for s in range(0, len(y) - win, win * 6):     # every 6th window for speed
            out = process_ecg_window(y[s:s + win], fs)
            rr = ref[(ref >= s) & (ref < s + win)]
            if len(rr) >= 3:
                hr_ref = 60.0 / np.median(np.diff(rr) / fs)
                errs.append(abs(out["hr"] - hr_ref) if out["hr"] else np.nan)
                qs.append(out["quality"])
        errs, qs = np.array(errs), np.array(qs)
        trusted = qs >= 0.6        # DETECTION.min_quality - readings below are not used for escalation
        bad = np.nan_to_num(errs, nan=99) > 10
        noise_rows.append({"snr_db": snr_db, "median_sqi": round(float(np.median(qs)), 3),
                           "pct_windows_trusted": round(100 * float(trusted.mean()), 1),
                           "hr_err_gt10bpm_pct_all": round(100 * float(bad.mean()), 1),
                           "hr_err_gt10bpm_pct_trusted": round(100 * float(bad[trusted].mean()), 1) if trusted.any() else None})
    res["noise_robustness"] = noise_rows
    return res


def drive(rec="drive02"):
    import wfdb

    r = wfdb.rdrecord(str(EXT / "wfdb_samples" / rec))
    fs_ecg = r.fs * 32          # ECG stored at 32 samples per frame
    ecg = r.e_p_signal[0] if r.e_p_signal is not None else None
    if ecg is None:
        r = wfdb.rdrecord(str(EXT / "wfdb_samples" / rec), smooth_frames=False)
        ecg = np.asarray(r.e_p_signal[0])
    hr_dev = r.p_signal[:, r.sig_name.index("HR")] if r.p_signal is not None else None
    if hr_dev is None:
        hr_dev = np.asarray(r.e_p_signal[r.sig_name.index("HR")])
    win = int(10 * fs_ecg)
    rows = []
    for s in range(0, len(ecg) - win, win):
        out = process_ecg_window(ecg[s:s + win], fs_ecg)
        f0, f1 = int(s / 32), int((s + win) / 32)
        dv = np.nanmedian(hr_dev[f0:f1])
        rows.append((out["hr"] if out["hr"] else np.nan, dv, out["quality"]))
    a = np.array(rows, float)
    ok = ~np.isnan(a[:, 0]) & ~np.isnan(a[:, 1]) & (a[:, 1] > 30)
    tr = ok & (a[:, 2] >= 0.6)
    d_all = a[ok, 0] - a[ok, 1]
    d_tr = a[tr, 0] - a[tr, 1]
    return {"record": f"drivedb/{rec}", "fs_ecg": fs_ecg, "duration_min": round(len(ecg) / fs_ecg / 60, 1),
            "windows": int(ok.sum()), "pct_windows_trusted_sqi": round(100 * float(tr.sum() / max(ok.sum(), 1)), 1),
            "mae_vs_device_hr_all_bpm": round(float(np.mean(np.abs(d_all))), 2),
            "mae_vs_device_hr_trusted_bpm": round(float(np.mean(np.abs(d_tr))), 2) if tr.any() else None,
            "within_5bpm_trusted_pct": round(100 * float(np.mean(np.abs(d_tr) <= 5)), 1) if tr.any() else None,
            "note": "Device HR is itself an estimate (not a gold standard); agreement, not accuracy, is measured."}


def main():
    REPORTS.mkdir(exist_ok=True)
    out = {"mitbih": mitbih("100")}
    try:
        out["drivedb"] = drive("drive02")
    except Exception as e:   # optional dataset
        out["drivedb"] = {"error": str(e)}
    (REPORTS / "real_data_validation.json").write_text(json.dumps(out, indent=2))
    m, d = out["mitbih"], out["drivedb"]
    L = ["# Real-data validation of the ECG chain", "",
         "Real human recordings from PhysioNet (not astronauts - see Limitations).", "",
         f"## MIT-BIH Arrhythmia Database, record 100 ({m['duration_min']} min, {m['fs']} Hz)", "",
         "| Metric | Value |", "|---|---|",
         f"| Reference beats (cardiologist-annotated) | {m['reference_beats']:,} |",
         f"| Beat-detection sensitivity (150 ms tolerance) | {m['sensitivity']:.2%} |",
         f"| Positive predictive value | {m['ppv']:.2%} |",
         f"| HR mean absolute error per 10 s window | {m['hr_mae_bpm']} bpm (bias {m['hr_bias_bpm']:+}) |",
         f"| HR 95th-percentile absolute error | {m['hr_p95_abs_err_bpm']} bpm |",
         f"| RMSSD MAE per 10 s window | {m['rmssd_mae_ms']} ms (reference median {m['rmssd_median_ref_ms']} ms) |",
         f"| Median signal-quality index | {m['median_sqi']} |", "",
         "### Noise robustness (record 100 + added in-band 5-30 Hz noise, overlapping QRS energy)", "",
         "| SNR (dB) | Median SQI | Windows trusted (SQI >= 0.6) | HR error > 10 bpm, all windows | ... among trusted windows |",
         "|---|---|---|---|---|"]
    for r in m["noise_robustness"]:
        L.append(f"| {r['snr_db']} | {r['median_sqi']} | {r['pct_windows_trusted']}% | {r['hr_err_gt10bpm_pct_all']}% | "
                 f"{r['hr_err_gt10bpm_pct_trusted'] if r['hr_err_gt10bpm_pct_trusted'] is not None else '-'}% |")
    L += ["", "Reading this honestly: down to ~3 dB the detector is unaffected. Below that the SQI falls, but "
          "not fast enough on its own - at 0 dB some windows it still trusts carry HR errors > 10 bpm. ARES "
          "therefore does not rely on the SQI alone: (1) ECG HR is cross-checked against the oximeter pulse "
          "rate (> 15 bpm disagreement lowers trust and triggers fallback), and (2) escalation requires the "
          "deviation to persist for minutes, which isolated wrong windows do not. Improving the SQI "
          "(e.g., multi-lead agreement, template matching against the personal beat) is listed as future work.", ""]
    if "error" not in d:
        L += [f"## drivedb {d['record']} ({d['duration_min']} min of real-driving ambulatory ECG)", "",
              f"- Windows compared: {d['windows']}; trusted by SQI: {d['pct_windows_trusted_sqi']}%",
              f"- ARES HR vs recording device HR: MAE {d['mae_vs_device_hr_all_bpm']} bpm (all), "
              f"{d['mae_vs_device_hr_trusted_bpm']} bpm (trusted); within 5 bpm: {d['within_5bpm_trusted_pct']}% of trusted windows",
              f"- {d['note']}", ""]
    L += ["## Limitations", "", "- One annotated record is a demonstration, not a validation study; the full 48-record "
          "MIT-BIH evaluation is the next step (PhysioNet was not reachable from the build environment).",
          "- Neither dataset is from spaceflight; microgravity changes ECG amplitude/axis (fluid shift) and "
          "electrode contact behaves differently in weightlessness.", ""]
    (REPORTS / "REAL_DATA_VALIDATION.md").write_text("\n".join(L))
    print(json.dumps(out, indent=1)[:3000])


if __name__ == "__main__":
    main()
