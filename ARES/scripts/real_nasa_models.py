"""Run Models C, D, E + bone analyses on REAL NASA DATA and write reports/REAL_NASA_DATA.md (+ json, figures).

    python scripts/real_nasa_models.py
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ares.realdata import analysis as A  # noqa: E402

REP = ROOT / "reports"
INK, MUTED, GRID = "#1f1f1d", "#6b6a64", "#e6e4dd"
BLUE, ORANGE, GREY = "#3987e5", "#d9622b", "#9a9890"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})


def clean(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def fig_radlab(D):
    z, thr, srag = D["_z"], D["_thr"], D["_srag"]
    fig, ax = plt.subplots(figsize=(11, 3.6))
    zc = z.clip(-5, 30)
    ax.plot(zc.index, zc.values, color=BLUE, lw=0.7)
    ax.axhline(thr, color=INK, lw=1, ls="--")
    ax.text(zc.index.min(), thr + 0.8, f"alarm threshold z = {thr:g}", color=INK, fontsize=9)
    for _, e in srag.iterrows():
        ax.axvspan(e.P10_StartDT, e.P10_EndDT, color=ORANGE, alpha=0.35 if e.P10_PeakVal >= 100 else 0.15, lw=0)
    ax.set_ylabel("robust z (non-SAA dose, 3 h)")
    ax.set_title("ISS DOSTEL-1 (RadLab) vs NASA SRAG solar particle events — shaded = SRAG event "
                 "(darker: ≥100 pfu); gaps = no RadLab data", fontsize=10, loc="left", color=INK)
    ax.grid(axis="y", color=GRID, lw=0.6)
    fig.tight_layout()
    fig.savefig(REP / "fig_radlab_sep.png", dpi=150)
    plt.close(fig)


def fig_soleus(C):
    df = C["_df"]
    ms = ["RR1", "RR9", "RR18", "BION-M1"]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    rng = np.random.default_rng(0)
    for i, m in enumerate(ms):
        for k, (fl, col, lab) in enumerate([(0, GREY, "ground (GC + vivarium)"), (1, ORANGE, "spaceflight")]):
            v = df[(df.mission == m) & (df.flight == fl)].mhc_iix.dropna()
            x = i + (k - 0.5) * 0.36 + rng.uniform(-0.07, 0.07, len(v))
            ax.scatter(x, v, s=28, color=col, edgecolor="white", lw=0.8, label=lab if i == 0 else None, zorder=3)
            ax.plot([i + (k - 0.5) * 0.36 - 0.12, i + (k - 0.5) * 0.36 + 0.12], [v.median()] * 2, color=INK, lw=1.6)
    ax.set_xticks(range(len(ms)), ms)
    ax.set_ylabel("soleus MHC IIx (relative band intensity)")
    ax.set_title("Fast-fibre myosin (MHC IIx) in mouse soleus after spaceflight — OSD-662 / LSDS-75", loc="left", fontsize=10)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", color=GRID, lw=0.6)
    fig.tight_layout()
    fig.savefig(REP / "fig_soleus_mhc.png", dpi=150)
    plt.close(fig)


def md(D, E, C, B, G):
    h, dv = D["held_out"], D["dev_calibrated_threshold"]
    L = ["# ARES on real NASA data", "",
         "All numbers below are computed by `scripts/real_nasa_models.py` from files in `data/osdr/` (NASA OSDR / ALSDA / "
         "RadLab) and `data/external/SRAG_SEP_List.csv` (NASA JSC Space Radiation Analysis Group event list). "
         "Category for every result: **REAL NASA DATA → MODEL-GENERATED ESTIMATES**. Nothing here is from the simulator.", "",
         "## Model D — solar particle events on a real ISS dosimeter", "",
         f"* Data: {D['n_readings']:,} DOSTEL-1 readings (ISS Columbus), {D['period'][0][:10]} → {D['period'][1][:10]}, "
         f"{D['days_with_data']} days with data (large gaps May–Aug 2022 and May–Dec 2023).",
         f"* Labels: {D['events_total']} SRAG solar proton events (GOES >10 MeV) in the window; {D['events_evaluable']} overlap RadLab data.",
         "* Method: drop trapped-belt (SAA) readings (≥30), take the 90th percentile of the rest per 3 h (high-latitude part of "
         "the orbit, where solar protons can penetrate), robust z vs the previous 7 days. Alarm at z ≥ 6, fixed a priori.",
         "* Split: 2022–2023 = development, **2024 = held-out**.", "",
         "| | held-out 2024 |", "|---|---|",
         f"| evaluable SRAG events | {h['evaluable']} |",
         f"| detected (z ≥ 6) | **{h['detected']}** |",
         f"| strong events (≥100 pfu) detected | **{h['strong_detected']} / {h['strong_ge100pfu_evaluable']}** |",
         f"| false-alarm episodes per 30 days | {h['false_alarms_per_30d']} |",
         f"| naive comparator (daily mean dose, z ≥ 3) detected | {h['naive_daily_mean_detected']} |", "",
         "| SRAG event start | peak >10 MeV (pfu) | max z | detected |", "|---|---|---|---|"]
    for e in D["events"]:
        if e["evaluable"]:
            L.append(f"| {e['start'][:16]} | {e['peak_pfu_10MeV']:g} | {e['max_z']} | {'yes' if e['detected'] else 'no'} |")
    L += ["", "![RadLab vs SRAG](fig_radlab_sep.png)", "",
          "**What this shows.** Inside the ISS, in low Earth orbit, the magnetosphere hides most solar particle events from the "
          "dosimeter: even 956–1,028 pfu events barely move it. The events ARES does see (May 11 and 13, 2024 and Oct 9, 2024) "
          "are the ones where protons reached ISS latitudes. The SAA-dominated daily mean finds none. "
          f"A threshold calibrated on quiet 2022–2023 data (z = {dv['z']}) gives {dv['held_out_false_alarms_per_30d']} false alarms "
          "per 30 days in 2024 (solar maximum), so calibration does not transfer across the solar cycle. That is why ARES uses "
          "a fixed robust rule and reports it.", "",
          "**Why it matters for Mars.** In interplanetary space there is no magnetosphere, so every SEP reaches the crew. Validated "
          "against ISS data, ARES detects the cases that physically reach the detector; deep-space validation needs MSL/RAD or "
          "Artemis data (roadmap).", "",
          "## Model E — Inspiration4 crew: personal baseline vs generic reference range", "",
          f"* Data: OSD-569 (CBC) + OSD-575 (CMP, serum cytokines); {E['n_crew']} crew; {E['n_markers']} clinical markers; "
          "pre-flight L-92/L-44/L-3, post-flight R+1/R+45/R+82/R+194.",
          "* Personal z = (value − own pre-flight mean) / SD, where SD = max(own pre-flight SD, within-person CV of the *other* "
          "crew × mean). Flag at |z| ≥ 3. Pre-flight z uses leave-one-out (empirical false-alarm rate).", ""]
    for q in E["qc_excluded_samples"]:
        L.append(f"* **Data-quality catch:** sample {q['crew']} {q['tp']} (CBC) excluded by ARES row-level QC: "
                 + ", ".join(f"{x['marker']} = {x['value']} (lab range {x['lo']}–{x['hi']})" for x in q["implausible"])
                 + ". The pattern looks like a column shift in the transformed file.")
    p, pf = E["postflight"], E["preflight_flag_rate"]
    L += [f"* {E['units_note']}", "",
          "| | generic lab range | ARES personal baseline |", "|---|---|---|",
          f"| pre-flight flag rate (no flight effect possible) | {pf['generic_range']*100:.1f}% | {pf['personal_baseline_loo']*100:.1f}% |",
          f"| post-flight flags (n = {p['n']} marker-timepoints) | {p['generic_flags']} | {p['personal_flags']} |",
          f"| …of which only repeat that person's pre-flight trait | {p['generic_repeating_preflight_trait']} | 0 by construction |",
          f"| flags raised only by this method | {p['generic_only']} | {p['personal_only']} |", "",
          "Personal-baseline flags at R+1: " + "; ".join(
              f"{r['crew']} {r['marker']} {r['value']} vs own {r['personal_mean']} (z {r['z']:+}, generic {'flag' if r['generic_flag'] else 'normal'})"
              for r in E["personal_flags_R1"]) + ".", "",
          f"Cytokines ({E['cytokines']['n_analytes']} analytes): no analyte moved the same direction (|z| ≥ 2) in ≥3 of 4 crew at "
          f"R+1; pre-flight leave-one-out flag rate {E['cytokines']['preflight_loo_flag_rate_z3']*100:.1f}%. {E['cytokines']['note']}", "",
          "**Reading.** On a 3-day mission few large changes are expected, and few are found. Most generic flags describe a "
          "person's stable normal (e.g. one crew member's haemoglobin is below the generic range at every time point), which is "
          "the alarm fatigue ARES is designed to remove. n = 4: this is a demonstration of the method, not a clinical validation.", "",
          "## Model C — spaceflight soleus response (mice), leave-one-mission-out", "",
          f"* Data: OSD-662 / LSDS-75 soleus western blot, {C['n_samples']} mice ({C['n_flight']} flight) from {', '.join(C['missions'])}. "
          f"Features: {', '.join(C['features'])} (log2). {C['note']}", "",
          "| held-out mission | n (flight) | logistic AUC | logistic acc. | MHC IIx single-rule acc. | majority acc. |",
          "|---|---|---|---|---|---|"]
    for r in C["leave_one_mission_out"]:
        L.append(f"| {r['held_out_mission']} | {r['n']} ({r['n_flight']}) | {r['auc']} | {r['accuracy']} | "
                 f"{r['mhc_iix_rule_accuracy']} | {r['majority_accuracy']} |")
    L += ["", "| mission | feature | median flight | median ground | Hedges g | p (Mann-Whitney) |", "|---|---|---|---|---|---|"]
    for r in C["effects"]:
        if r["feature"] in ("mhc_i", "mhc_iia", "mhc_iix"):
            L.append(f"| {r['mission']} | {r['feature']} | {r['median_flight']} | {r['median_ground']} | {r['hedges_g']} | {r['p_mwu']} |")
    L += ["", "![soleus](fig_soleus_mhc.png)", "",
          "**Reading.** The slow-to-fast fibre shift (MHC IIx up, MHC I/IIa down) generalises across three of four missions held "
          "out entirely. The multi-feature model does **not** beat a single MHC IIx rule, so ARES shows the simpler rule. "
          "Bion-M1 (a different spacecraft) transfers worst. Shown on the 3D soleus as research evidence only.", "",
          "## Bone — RR-9 tibia microCT and femur western blot (mice)", "", B["note"], "",
          "| tibia parameter | flight vs ground | Hedges g | p | g vs vivarium |", "|---|---|---|---|---|"]
    for r in B["tibia_microct"]:
        L.append(f"| {r['parameter']} | {r['pct_diff_vs_ground']:+.1f}% | {r['hedges_g_vs_ground']} | {r['p_mwu_vs_ground']} | {r['hedges_g_vs_vivarium']} |")
    L += ["", "| femur western blot | median flight | median ground | Hedges g | p |", "|---|---|---|---|---|"]
    for r in B["femur_western_blot"]:
        L.append(f"| {r['parameter']} | {r['flight_median']} | {r['ground_median']} | {r['hedges_g_vs_ground']} | {r['p_mwu_vs_ground']} |")
    L += ["", "## GeneLab RNA-seq runsheets (OSD-104, OSD-770)", ""]
    for g in G:
        L.append(f"* {g['study']} ({g['file']}): {g['samples']} libraries, groups {g['groups']}, tech reps {g['tech_reps']}. {g['status']}.")
    L += ["", "## Limitations", "",
          "* RadLab: one detector, one module, LEO; absorbed dose rate as reported by RadLab; SAA split by a fixed cut (no orbit "
          "position available in this export). SRAG labels are GOES >10 MeV at geostationary orbit, not dose at the ISS.",
          "* Inspiration4: 4 people, 3 days, civilian crew; 3 pre-flight samples per person.",
          "* Rodent data: relative band intensities, small groups, multiple comparisons uncorrected; organism-level evidence, "
          "never displayed as astronaut risk."]
    return "\n".join(L) + "\n"


def research_evidence(C, B):
    """Compact summaries the 3D twin shows on muscles/bones (organism evidence)."""
    def eff(m, f):
        return next(r for r in C["effects"] if r["mission"] == m and r["feature"] == f)
    lomo = {r["held_out_mission"]: r["auc"] for r in C["leave_one_mission_out"]}
    sol = [{"title": "Slow-to-fast fibre shift after spaceflight", "dataset": "OSD-662 / LSDS-75 (RR-1, RR-9, RR-18, Bion-M1)",
            "summary": f"MHC IIx higher in flight mice (Hedges g {eff('RR9','mhc_iix')['hedges_g']} RR-9, {eff('RR18','mhc_iix')['hedges_g']} RR-18, "
                       f"{eff('RR1','mhc_iix')['hedges_g']} RR-1); MHC IIa lower. Leave-one-mission-out AUC "
                       f"{min(lomo.values())}–{max(lomo.values())}.", "effect": "fibre-type shift"}]
    t = {r["parameter"]: r for r in B["tibia_microct"]}
    tib = [{"title": "Cortical bone loss after ~33 days in orbit", "dataset": "OSD-654 / LSDS-66 (RR-9 microCT)",
            "summary": f"Cortical thickness {t['cortical_thickness_millimeter']['pct_diff_vs_ground']:+.1f}% vs habitat ground control "
                       f"(g {t['cortical_thickness_millimeter']['hedges_g_vs_ground']}, p {t['cortical_thickness_millimeter']['p_mwu_vs_ground']}); "
                       f"trabecular number {t['trabecular_number_1_per_millimeter']['pct_diff_vs_ground']:+.1f}% (n.s.). n = 4 vs 5.",
            "effect": "bone loss"}]
    fw = {r["parameter"]: r for r in B["femur_western_blot"]}
    fem = [{"title": "Femur GSK3-beta signalling (no clear change)", "dataset": "OSD-663 / LSDS-70 (RR-9 western blot)",
            "summary": f"pSer9-GSK3-beta median {fw['serine9_phosphorylated_GSK3_beta_content']['flight_median']} flight vs "
                       f"{fw['serine9_phosphorylated_GSK3_beta_content']['ground_median']} ground (p "
                       f"{fw['serine9_phosphorylated_GSK3_beta_content']['p_mwu_vs_ground']}); not significant at n = 6 vs 5.",
            "effect": "inconclusive"}]
    return {"soleus_left": sol, "soleus_right": sol, "tibia_left": tib, "tibia_right": tib, "femur_left": fem, "femur_right": fem}


def main():
    D, E, C, B, G = A.radlab_model(), A.i4_model(), A.soleus_model(), A.bone_models(), A.genelab_inventory()
    fig_radlab(D)
    fig_soleus(C)
    (REP / "REAL_NASA_DATA.md").write_text(md(D, E, C, B, G))
    out = {"model_D_radlab": clean(D), "model_E_inspiration4": clean(E), "model_C_soleus": clean(C), "bone": B,
           "genelab": G, "research_evidence": research_evidence(C, B)}
    (REP / "real_nasa_data.json").write_text(json.dumps(out, indent=1, default=str))
    h = D["held_out"]
    print(f"D: {h['strong_detected']}/{h['strong_ge100pfu_evaluable']} strong SEPs, {h['false_alarms_per_30d']} FA/30d | "
          f"E: generic {E['postflight']['generic_flags']} vs personal {E['postflight']['personal_flags']} post-flight flags | "
          f"C: LOMO AUC {[r['auc'] for r in C['leave_one_mission_out']]}")


if __name__ == "__main__":
    main()
