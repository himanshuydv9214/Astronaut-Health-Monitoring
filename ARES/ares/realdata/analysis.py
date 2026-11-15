"""Analyses on REAL NASA DATA (OSDR / ALSDA / RadLab) + NASA JSC SRAG event labels.

Model D  RadLab DOSTEL-1 (ISS Columbus) -> solar particle event visibility / detection vs SRAG SEP list
Model E  Inspiration4 crew CBC + CMP + serum cytokines -> personal baseline vs generic reference range
Model C  Rodent Research soleus (RR-1, RR-9, RR-18, Bion-M1) -> flight vs ground, leave-one-mission-out
Bone     RR-9 tibia microCT, femur western blot -> effect sizes (descriptive)

No numbers in this file are invented: every value is computed from the files in data/osdr and data/external.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OSDR = ROOT / "data" / "osdr"
EXT = ROOT / "data" / "external"
PRE = ["L-92", "L-44", "L-3"]
POST = ["R+1", "R+45", "R+82", "R+194"]
TP_ORDER = PRE + POST


# ----------------------------------------------------------------------------------------- helpers
def hedges_g(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    sp = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    if sp == 0:
        return float("nan")
    j = 1 - 3 / (4 * (len(a) + len(b)) - 9)
    return float(j * (a.mean() - b.mean()) / sp)


def mwu_p(a, b) -> float:
    from scipy.stats import mannwhitneyu
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)


# ----------------------------------------------------------------------------------------- Model D
def load_radlab() -> pd.Series:
    d = pd.read_csv(OSDR / "radlab_dostel1.csv", sep="\t", parse_dates=["timestamp"])
    return d.set_index("timestamp")["absorbed_dose_rate"].sort_index()


def load_srag(start, end) -> pd.DataFrame:
    s = pd.read_csv(EXT / "SRAG_SEP_List.csv", parse_dates=["P10_StartDT", "P10_PeakDT", "P10_EndDT"])
    s = s[(s.P10_StartDT >= start) & (s.P10_StartDT <= end)].copy()
    s["P10_EndDT"] = s["P10_EndDT"].fillna(s["P10_StartDT"] + pd.Timedelta(hours=6))
    return s.reset_index(drop=True)


def radlab_model(saa_cut: float = 30.0, window: str = "3h", base: str = "7D", dev_end: str = "2023-12-31",
                 z_alarm: float = 6.0) -> dict:
    """Robust change detection on the non-SAA part of the dose-rate distribution.

    readings >= saa_cut are treated as trapped-belt (SAA) passes and excluded; per window we take the 90th
    percentile of the remaining readings (the high-latitude part of each orbit, where solar protons can enter)
    and compare it with a trailing robust baseline (median / MAD of the previous 7 days).
    Operating threshold: robust z >= 6, fixed a priori (not tuned on events). For comparison we also report a threshold
    calibrated on the 2022-2023 non-event windows (0.1% false-alarm quantile): it fails on 2024 because solar-maximum
    variability shifts the distribution - a documented limitation, not hidden.
    """
    d = load_radlab()
    lo = d[d < saa_cut]
    feat = lo.resample(window).agg(lambda x: np.percentile(x, 90) if len(x) >= 60 else np.nan)
    med = feat.rolling(base, min_periods=20).median().shift(1)
    mad = (feat - med).abs().rolling(base, min_periods=20).median().shift(1)
    z = (feat - med) / (1.4826 * mad + 1e-9)
    srag = load_srag(d.index.min(), d.index.max())
    in_event = pd.Series(False, index=z.index)
    for _, e in srag.iterrows():
        in_event |= (z.index >= e.P10_StartDT.floor(window)) & (z.index <= e.P10_EndDT)
    dev = z.index <= dev_end
    thr_dev = float(np.nanquantile(z[dev & ~in_event.values], 0.999))
    thr = z_alarm
    events = []
    for _, e in srag.iterrows():
        m = (z.index >= e.P10_StartDT.floor(window)) & (z.index <= e.P10_EndDT)
        zz = z[m].dropna()
        events.append({"start": str(e.P10_StartDT), "peak_pfu_10MeV": float(e.P10_PeakVal),
                       "dst_nT": None if pd.isna(e.get("DST")) else float(e.get("DST")),
                       "evaluable": bool(len(zz)), "max_z": None if zz.empty else round(float(zz.max()), 1),
                       "detected": bool(len(zz)) and float(zz.max()) >= thr,
                       "split": "development" if e.P10_StartDT <= pd.Timestamp(dev_end) else "held-out 2024"})
    ev = pd.DataFrame(events)
    alarms = (z >= thr) & ~in_event
    # merge consecutive alarm windows into alarm episodes
    ep = (alarms & ~alarms.shift(1, fill_value=False)).sum()
    days_cov = float(feat.notna().sum() * pd.Timedelta(window) / pd.Timedelta("1D"))
    test = ev[ev.split == "held-out 2024"]
    te = test[test.evaluable]
    strong = te[te.peak_pfu_10MeV >= 100]
    held_alarms = int((alarms & (z.index > dev_end)).astype(int).diff().clip(lower=0).sum())
    held_days = float(feat[z.index > dev_end].notna().sum() * pd.Timedelta(window) / pd.Timedelta("1D"))
    # naive comparator: daily mean dose rate (SAA-dominated) with the same procedure
    day_mean = d.resample("D").mean()
    dm = day_mean.where(d.resample("D").count() >= 500)
    dmed = dm.rolling("27D", min_periods=10).median().shift(1)
    dmad = (dm - dmed).abs().rolling("27D", min_periods=10).median().shift(1)
    dz = (dm - dmed) / (1.4826 * dmad + 1e-9)
    naive_det = 0
    for _, e in srag[srag.P10_StartDT > dev_end].iterrows():
        m = (dz.index >= e.P10_StartDT.floor("D")) & (dz.index <= e.P10_EndDT)
        if dz[m].notna().any() and dz[m].max() >= 3:
            naive_det += 1
    return {
        "source": "OSDR RadLab, DOSTEL-1 (ISS Columbus), absorbed_dose_rate as reported by RadLab",
        "labels": "NASA JSC SRAG SEP list (GOES >10 MeV), via github.com/ktindiana/fetchsep reference/SRAG_SEP_List.csv",
        "n_readings": int(len(d)), "period": [str(d.index.min()), str(d.index.max())],
        "days_with_data": round(days_cov, 1), "threshold_z": round(thr, 2),
        "events_total": int(len(ev)), "events_evaluable": int(ev.evaluable.sum()),
        "held_out": {"events": int(len(test)), "evaluable": int(len(te)), "detected": int(te.detected.sum()),
                     "strong_ge100pfu_evaluable": int(len(strong)), "strong_detected": int(strong.detected.sum()),
                     "false_alarm_episodes": held_alarms, "days": round(held_days, 1),
                     "false_alarms_per_30d": round(held_alarms / max(held_days, 1) * 30, 2),
                     "naive_daily_mean_detected": naive_det},
        "dev_calibrated_threshold": {"z": round(thr_dev, 2),
            "held_out_false_alarms_per_30d": round(int(((z >= thr_dev) & ~in_event & (z.index > dev_end)).astype(int).diff().clip(lower=0).sum())
                                                   / max(held_days, 1) * 30, 1)},
        "development": {"evaluable": int(ev[(ev.split == "development") & ev.evaluable].shape[0]),
                        "detected": int(ev[(ev.split == "development") & ev.detected].shape[0])},
        "events": events, "_z": z, "_thr": thr, "_srag": srag, "_alarm_episodes_total": int(ep),
    }


# ----------------------------------------------------------------------------------------- Model E
_TP = re.compile(r"(C\d{3})_.*?_(L-\d+|R\+\d+)")


def _wide_labs(path: Path) -> tuple[pd.DataFrame, dict]:
    """Returns long table (crew, tp, marker, value, lo, hi) and units map."""
    df = pd.read_csv(path, na_values=["NA", "N/A", ""])
    rows, units = [], {}
    for col in df.columns:
        m = re.match(r"(.+?)_value_(.+)", col)
        if not m:
            continue
        key, unit = m.group(1), m.group(2)
        lo_c = next((c for c in df.columns if c.startswith(key + "_range_min")), None)
        hi_c = next((c for c in df.columns if c.startswith(key + "_range_max") or c.startswith(key + "_max")), None)
        units[key] = unit
        for _, r in df.iterrows():
            mm = _TP.search(r["Sample Name"])
            if not mm:
                continue
            rows.append({"crew": mm.group(1), "tp": mm.group(2), "marker": key,
                         "value": pd.to_numeric(r[col], errors="coerce"),
                         "lo": pd.to_numeric(r[lo_c], errors="coerce") if lo_c else np.nan,
                         "hi": pd.to_numeric(r[hi_c], errors="coerce") if hi_c else np.nan})
    return pd.DataFrame(rows), units


def _cytokines(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, na_values=["NA", "N/A", ""])
    rows = []
    for col in df.columns:
        if not col.endswith("_concentration_picogram_per_milliliter"):
            continue
        key = col.replace("_concentration_picogram_per_milliliter", "")
        for _, r in df.iterrows():
            mm = _TP.search(r["Sample Name"])
            if mm:
                rows.append({"crew": mm.group(1), "tp": mm.group(2), "marker": key,
                             "value": pd.to_numeric(r[col], errors="coerce"), "lo": np.nan, "hi": np.nan})
    return pd.DataFrame(rows)


CBC_KEEP = ["white_blood_cell_count", "red_blood_cell_count", "hemoglobin", "hematocrit", "platelet_count",
            "absolute_lymphocytes", "absolute_neutrophils", "absolute_monocytes", "absolute_eosinophils", "mcv", "rdw", "mpv"]
CMP_KEEP = ["albumin", "alkaline_phosphatase", "alt", "ast", "total_bilirubin", "calcium", "carbon_dioxide", "chloride",
            "creatinine", "globulin", "glucose", "potassium", "total_protein", "sodium", "urea_nitrogen_bun"]


def qc_rows(long: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Row-level plausibility QC: a sample is excluded if >= 2 markers are > 3x the lab's upper limit or < 1/3 of
    its lower limit (physiologically implausible for a healthy adult -> likely transcription/column shift)."""
    bad = long[(long.hi.notna() & (long.value > 3 * long.hi)) | (long.lo.notna() & (long.lo > 0) & (long.value < long.lo / 3))]
    n = bad.groupby(["crew", "tp"]).size()
    excl = [k for k, v in n.items() if v >= 2]
    notes = [{"crew": c, "tp": t, "implausible": bad[(bad.crew == c) & (bad.tp == t)][["marker", "value", "lo", "hi"]]
              .round(2).to_dict("records")} for c, t in excl]
    mask = long.set_index(["crew", "tp"]).index.isin(excl)
    return long[~mask].copy(), notes


def _pooled_cv(long: pd.DataFrame) -> dict:
    """Within-person coefficient of variation per (crew, marker), estimated from the OTHER crew members'
    pre-flight samples (leave-one-crew-out), so a person's own data never sets their own tolerance."""
    pre = long[long.tp.isin(PRE)].dropna(subset=["value"])
    st = pre.groupby(["marker", "crew"]).value.agg(["var", "mean", "count"])
    st = st[(st["count"] >= 2) & (st["mean"].abs() > 0)]
    st["cv2"] = st["var"] / st["mean"] ** 2
    out = {}
    for (m, c) in st.index:
        others = st.loc[m].drop(index=c, errors="ignore")
        out[(c, m)] = float(np.sqrt(others.cv2.mean())) if len(others) else float("nan")
    return out


def personal_baseline(long: pd.DataFrame, floor_cv: float, z_thr: float = 3.0) -> pd.DataFrame:
    """z of each sample vs that crew member's own pre-flight samples.
    SD = max(own pre-flight SD, pooled within-person CV of the other crew x mean, floor_cv x mean).
    Pre-flight z values use leave-one-out (other pre-flight samples only) -> empirical false-alarm rate."""
    cvp = _pooled_cv(long)
    out = []
    for (c, m), g in long.groupby(["crew", "marker"]):
        g = g.dropna(subset=["value"]).set_index("tp")
        for tp, r in g.iterrows():
            ref = g.loc[[t for t in PRE if t in g.index and t != tp], "value"]
            if len(ref) < 2:
                continue
            mu = ref.mean()
            cv = cvp.get((c, m), float("nan"))
            sd = max(ref.std(ddof=1), (0 if np.isnan(cv) else cv) * abs(mu), floor_cv * abs(mu), 1e-9)
            z = (r.value - mu) / sd
            gen = (pd.notna(r.lo) and r.value < r.lo) or (pd.notna(r.hi) and r.value > r.hi)
            out.append({"crew": c, "marker": m, "tp": tp, "value": r.value, "personal_mean": mu, "z": z,
                        "personal_flag": abs(z) >= z_thr, "generic_flag": bool(gen), "pre": tp in PRE})
    return pd.DataFrame(out)


def i4_model() -> dict:
    cbc, u1 = _wide_labs(OSDR / "LSDS-7_Complete_Blood_Count_CBC_TRANSFORMED.csv")
    cmp_, u2 = _wide_labs(OSDR / "LSDS-8_Comprehensive_Metabolic_Panel_CMP_TRANSFORMED.csv")
    cyt = _cytokines(OSDR / "LSDS-8_Multiplex_serum_immune_EvePanel_TRANSFORMED.csv")
    cbc = cbc[cbc.marker.isin(CBC_KEEP)]
    cmp_ = cmp_[cmp_.marker.isin(CMP_KEEP)]
    cbc_q, qc_notes = qc_rows(cbc)
    clinical = pd.concat([cbc_q.assign(panel="CBC"), cmp_.assign(panel="CMP")])
    pb = personal_baseline(clinical, floor_cv=0.02)
    pb = pb.merge(clinical[["crew", "marker", "panel"]].drop_duplicates(), on=["crew", "marker"])
    pre, post = pb[pb.pre], pb[~pb.pre]
    res = {
        "n_crew": int(pb.crew.nunique()), "n_markers": int(pb.marker.nunique()),
        "qc_excluded_samples": qc_notes,
        "preflight_flag_rate": {"generic_range": round(float(pre.generic_flag.mean()), 3),
                                "personal_baseline_loo": round(float(pre.personal_flag.mean()), 3),
                                "n": int(len(pre))},
        "postflight": {"generic_flags": int(post.generic_flag.sum()), "personal_flags": int(post.personal_flag.sum()),
                       "personal_only": int((post.personal_flag & ~post.generic_flag).sum()),
                       "generic_only": int((post.generic_flag & ~post.personal_flag).sum()),
                       "both": int((post.generic_flag & post.personal_flag).sum()), "n": int(len(post)),
                       "generic_repeating_preflight_trait": int(sum(1 for _, r in post[post.generic_flag].iterrows()
                           if pre[(pre.crew == r.crew) & (pre.marker == r.marker)].generic_flag.any()))},
        "by_timepoint": {tp: {"personal": int(post[post.tp == tp].personal_flag.sum()),
                              "generic": int(post[post.tp == tp].generic_flag.sum()),
                              "n": int((post.tp == tp).sum())} for tp in POST},
        "personal_flags_R1": post[(post.tp == "R+1") & post.personal_flag]
            .sort_values("z", key=abs, ascending=False)[["crew", "marker", "value", "personal_mean", "z", "generic_flag"]]
            .round(2).to_dict("records"),
        "generic_preflight_examples": pre[pre.generic_flag][["crew", "marker", "tp", "value"]].round(2).head(12).to_dict("records"),
        "units_note": "LSDS-7 labels hemoglobin 'percent'; values and range (13.2-17.1) are g/dL.",
    }
    # cytokines: report analytes moving the same direction in >=3 of 4 crew at R+1
    cz = personal_baseline(cyt, floor_cv=0.05)
    r1 = cz[cz.tp == "R+1"]
    cons = []
    for m, g in r1.groupby("marker"):
        up, dn = int((g.z >= 2).sum()), int((g.z <= -2).sum())
        if max(up, dn) >= 3:
            cons.append({"analyte": m, "direction": "up" if up >= dn else "down", "crew": max(up, dn),
                         "median_z": round(float(g.z.median()), 1)})
    res["cytokines"] = {"n_analytes": int(cyt.marker.nunique()), "R1_consistent_ge3of4": cons,
                        "preflight_loo_flag_rate_z3": round(float(cz[cz.pre].personal_flag.mean()), 3),
                        "note": "Exploratory: 71 analytes x 4 crew, no multiplicity correction; shown as hypotheses only."}
    res["_pb"] = pb
    return res


# ----------------------------------------------------------------------------------------- Model C (soleus)
def soleus_model() -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    df = pd.read_csv(OSDR / "LSDS-75_western-blot_soleus_westernblot_TRANSFORMED.csv")
    df = df[df["Sample Name"].str.match(r"^(RR1|RR9|RR18|BION-M1)_")].copy()
    df["mission"] = df["Sample Name"].str.extract(r"^(RR1|RR9|RR18|BION-M1)_")[0]
    df["group"] = df["Sample Name"].str.extract(r"^[A-Z0-9-]+_(F|GC|VIV)_")[0]
    df["flight"] = (df.group == "F").astype(int)
    feats = ["mhc_i", "mhc_iia", "mhc_iix"]          # measured in all four missions
    eff = []
    for mis, g in df.groupby("mission"):
        for f in feats + ["mhc_iib", "GSK3_beta_content"]:
            a, b = g[g.flight == 1][f], g[g.flight == 0][f]
            if a.notna().sum() >= 2 and b.notna().sum() >= 2:
                eff.append({"mission": mis, "feature": f, "n_flight": int(a.notna().sum()), "n_ground": int(b.notna().sum()),
                            "median_flight": round(float(a.median()), 3), "median_ground": round(float(b.median()), 3),
                            "hedges_g": round(hedges_g(a, b), 2), "p_mwu": round(mwu_p(a, b), 4)})
    X = np.log2(df[feats].clip(lower=0.01))
    y = df.flight.values
    lomo, rule = [], []
    for mis in df.mission.unique():
        tr, te = df.mission != mis, df.mission == mis
        med = X[tr].median()
        Xtr, Xte = X[tr].fillna(med), X[te].fillna(med)
        mu, sd = Xtr.mean(), Xtr.std().replace(0, 1)
        clf = LogisticRegression(C=1.0, max_iter=1000).fit((Xtr - mu) / sd, y[tr])
        p = clf.predict_proba((Xte - mu) / sd)[:, 1]
        auc = roc_auc_score(y[te], p) if len(set(y[te])) == 2 else float("nan")
        # single-feature comparator: MHC IIx, threshold = midpoint of training-group medians
        xi = df.loc[tr, "mhc_iix"]
        t = (xi[y[tr] == 1].median() + xi[y[tr] == 0].median()) / 2
        xi_te = df.loc[te, "mhc_iix"].fillna(xi.median())
        lomo.append({"held_out_mission": mis, "n": int(te.sum()), "n_flight": int(y[te].sum()), "auc": round(float(auc), 3),
                     "accuracy": round(float(((p >= 0.5).astype(int) == y[te]).mean()), 3),
                     "mhc_iix_rule_accuracy": round(float(((xi_te >= t).astype(int) == y[te]).mean()), 3),
                     "majority_accuracy": round(float(max(y[te].mean(), 1 - y[te].mean())), 3)})
    return {"n_samples": int(len(df)), "n_flight": int(y.sum()), "missions": sorted(df.mission.unique().tolist()),
            "features": feats, "effects": eff, "leave_one_mission_out": lomo,
            "note": "Relative western-blot band intensities (normalised within study); mice, not humans. "
                    "In RR-1 rows the GSK3-beta and pSer9 columns are identical, so GSK3 is not used as a feature.",
            "_df": df}


# ----------------------------------------------------------------------------------------- bone
def bone_models() -> dict:
    ct = pd.read_csv(OSDR / "LSDS-66_microCT_uCT_TRANSFORMED.csv")
    ct.columns = [c.strip() for c in ct.columns]
    ct["group"] = ct["Sample Name"].str.replace(r"\d+$", "", regex=True)
    names = {"F": "Space Flight", "GC": "Ground Control (habitat)", "Viv": "Vivarium", "CC": "Cohort Control 2", "FViv": "Cohort Control 1"}
    tib = []
    for f in [c for c in ct.columns if c not in ("Sample Name", "group")]:
        a, b, v = ct[ct.group == "F"][f], ct[ct.group == "GC"][f], ct[ct.group == "Viv"][f]
        tib.append({"parameter": f, "flight_mean": round(float(a.mean()), 4), "ground_mean": round(float(b.mean()), 4),
                    "pct_diff_vs_ground": round(float((a.mean() / b.mean() - 1) * 100), 1),
                    "hedges_g_vs_ground": round(hedges_g(a, b), 2), "p_mwu_vs_ground": round(mwu_p(a, b), 3),
                    "hedges_g_vs_vivarium": round(hedges_g(a, v), 2), "n_flight": int(a.notna().sum()), "n_ground": int(b.notna().sum())})
    wb = pd.read_csv(OSDR / "LSDS-70_western-blot_Western_blot_femur_TRANSFORMED.csv")
    wb["group"] = wb["Sample Name"].str.replace(r"\d+$", "", regex=True)
    fem = []
    for f in wb.columns[1:-1]:
        a, b = wb[wb.group == "F"][f], wb[wb.group == "GC"][f]
        fem.append({"parameter": f, "flight_median": round(float(a.median()), 3), "ground_median": round(float(b.median()), 3),
                    "hedges_g_vs_ground": round(hedges_g(a, b), 2), "p_mwu_vs_ground": round(mwu_p(a, b), 3),
                    "n_flight": int(a.notna().sum()), "n_ground": int(b.notna().sum())})
    return {"tibia_microct": tib, "tibia_groups": {k: names[k] for k in names}, "femur_western_blot": fem,
            "note": "RR-9 (SpaceX-12) mice, ~33 days; n = 4-6 per group; descriptive effect sizes, no multiplicity correction."}


# ----------------------------------------------------------------------------------------- GeneLab runsheets
def genelab_inventory() -> list[dict]:
    out = []
    for f in sorted(OSDR.glob("GLDS-*_runsheet.csv")):
        d = pd.read_csv(f)
        fac = d["Factor Value[Spaceflight]"].value_counts().to_dict()
        out.append({"file": f.name, "samples": int(len(d)), "groups": fac,
                    "tech_reps": int(d["Has Tech Reps"].astype(str).eq("True").sum()),
                    "study": re.search(r"studies/(OSD-\d+)", d.read1_path.iloc[0]).group(1),
                    "status": "metadata only (sample design + raw FASTQ links); expression model needs the GeneLab "
                              "normalised-counts table, not processed in this build"})
    return out
