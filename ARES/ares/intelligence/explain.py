"""Explanations for every alert: what changed, vs which baseline, how sure, what's missing."""

from __future__ import annotations

from ares.config import DETECTION, PARAMS, VITAL_KEYS


def explain_state(st: dict, cls: dict, shap_top: list[dict] | None = None, baseline_n_min: int = 60) -> dict:
    baseline_text, changed, missing = [], [], []
    for k in VITAL_KEYS:
        v, z = st["values"].get(k), st["z"].get(k)
        spec = PARAMS[k]
        if v is None:
            missing.append(f"{spec.label} (no valid reading; quality {st['quality'][k]:.2f})")
            continue
        if st["age_min"].get(k):
            missing.append(f"{spec.label} last measured {st['age_min'][k]:.0f} min ago")
        if z is not None and abs(z) >= 2:
            lo, hi = st["band"][k]
            baseline_text.append(f"{spec.label}: {v:.1f} {spec.unit} vs this astronaut's usual {st['expected'][k]:.1f} "
                                 f"({lo:.1f}-{hi:.1f}) in '{st['context']}' context; z={z:+.1f}")
        sl, sd = st["slope_h"][k], st["slope_sd_h"][k]
        if sd > 0 and abs(sl) > 3 * sd and z is not None and abs(z) >= 1.5:
            changed.append(f"{spec.label} trending {sl:+.2f} {spec.unit}/h (+/-{sd:.2f})")
    for f in st["faults"]:
        if "missing" not in f:
            missing.append(f"Sensor issue: {f}")
    if st.get("hr_source", "ecg") != "ecg":
        missing.append(f"Heart rate from {st['hr_source']}; HRV unavailable")
    return {
        "influencing_parameters": shap_top or [],
        "baseline_text": baseline_text,
        "significant_changes": changed,
        "confidence": {"score": cls["confidence"], "label": cls["confidence_label"]},
        "missing": missing,
        "context": st["context"],
        "note": f"Personal baselines use a Bayesian model gated at |z|>{DETECTION.baseline_gate_z}; "
                "model attributions are SHAP values from the simulation-trained forecaster.",
    }
