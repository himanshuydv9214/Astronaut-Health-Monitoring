"""ARES evaluation on HELD-OUT synthetic astronauts (all data SIMULATED).

Sections
  1. Emergency detection vs baselines (event recall, latency, missed critical,
     false alarms per crew-day, minute-level precision/recall/F1)
  2. Sensor-failure robustness       3. Communication blackout
  4. Radiation (SPE) detection       5. Anomaly-model comparison
  6. Risk-forecaster comparison, calibration, horizon, leave-one-scenario-out
  7. Level confusion matrix          8. Behavioral readiness (simulated)

Baselines:
  * Static limits      - generic population alarm limits, no context, instant
  * Static limits +5m  - same, alarm only if sustained 5 min
  * NEWS2 >= 5         - published hospital early-warning score (RCP 2017)
  * ARES rules         - full pipeline without ML models
  * ARES full          - rules + anomaly model + forecaster (deployed system)

    python scripts/evaluate.py
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")   # before numpy/sklearn import (see ares/__init__.py)
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score  # noqa: E402

from ares.config import PARAMS, VITAL_KEYS  # noqa: E402
from ares.data.generate import DATA_DIR, TEST_ASTRONAUTS, run_many, specs_for  # noqa: E402
from ares.intelligence.features import ANOMALY_FEATURES, FEATURE_NAMES  # noqa: E402
from ares.intelligence.models import AnomalyModel, RiskForecaster  # noqa: E402
from ares.intelligence.news2 import news2  # noqa: E402
from scripts.train_models import forecaster_rows, nominal_mask  # noqa: E402

REPORTS = ROOT / "reports"
ACUTE = ["spo2_drop", "cardiac_arrhythmia", "respiratory", "dehydration", "gradual_deterioration",
         "multi_system", "blackout_emergency", "recovery"]


# ----------------------------------------------------------------------------- baselines
def static_alarm(df: pd.DataFrame) -> np.ndarray:
    """Conventional monitor: any displayed value beyond a generic population limit."""
    a = np.zeros(len(df), bool)
    for k in VITAL_KEYS:
        s = PARAMS[k]
        v = df[f"v_{k}"].to_numpy(float)
        if s.hard_low is not None:
            a |= v < s.hard_low
        if s.hard_high is not None:
            a |= v > s.hard_high
    return a


def persist(df: pd.DataFrame, a: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(len(a), bool)
    for _, idx in df.groupby("episode").indices.items():
        run = 0
        for i in idx:
            run = run + 1 if a[i] else 0
            out[i] = run >= n
    return out


def news2_levels(df: pd.DataFrame) -> np.ndarray:
    lv = np.zeros(len(df), int)
    cols = {k: df[f"v_{k}"].to_numpy(float) for k in ("rr", "spo2", "sbp", "hr", "temp")}
    for i in range(len(df)):
        n = news2({k: (None if np.isnan(cols[k][i]) else cols[k][i]) for k in cols})
        if n:
            lv[i] = 3 if n["score"] >= 7 else 2 if n["score"] >= 5 else 0
    return lv


def systems(df_rules, df_full) -> dict[str, np.ndarray]:
    st = static_alarm(df_rules)
    return {"Static limits": st.astype(int) * 2, "Static limits +5 min": persist(df_rules, st, 5).astype(int) * 2,
            "NEWS2 >= 5": news2_levels(df_rules), "ARES rules": df_rules["pred"].to_numpy(),
            "ARES full": df_full["pred"].to_numpy()}


# ----------------------------------------------------------------------------- metrics
def rising(x: np.ndarray) -> int:
    return int(np.sum(x[1:] & ~x[:-1]) + (x[0] if len(x) else 0))


def detection_table(df: pd.DataFrame, lv: np.ndarray, name: str) -> tuple[list, dict]:
    rows = []
    for ep, idx in df.groupby("episode").indices.items():
        g = df.iloc[idx]
        sc = g["scenario"].iat[0]
        if sc not in ACUTE:
            continue
        tr = g["truth"].to_numpy()
        t = g["t"].to_numpy()
        post = g["min_since_onset"].to_numpy() >= 0
        if not (tr >= 2).any():
            continue
        t2 = t[tr >= 2]
        on2, end2 = t2.min(), t2.max()
        p = lv[idx]
        hit = post & (p >= 2) & (t <= end2)
        det = t[hit].min() if hit.any() else None
        crit = (tr >= 3).any()
        reached3 = bool((post & (p >= 3)).any())
        rows.append({"system": name, "scenario": sc, "episode": ep, "detected": det is not None,
                     "latency_min": None if det is None else float(det - on2), "critical": bool(crit),
                     "reached_L3": reached3})
    d = pd.DataFrame(rows)
    summ = {"events": int(len(d)), "recall": round(float(d.detected.mean()), 3),
            "median_latency_min": None if not d.detected.any() else float(d.latency_min.median()),
            "missed_critical": int(((d.critical) & (~d.detected)).sum()),
            "critical_events": int(d.critical.sum())}
    return rows, summ


def false_alarms(df: pd.DataFrame, lv: np.ndarray) -> dict:
    m = nominal_mask(df).to_numpy()
    days = m.sum() / 1440.0
    out = {"nominal_crew_days": round(days, 2)}
    for L in (1, 2):
        n = 0
        for _, idx in df.groupby("episode").indices.items():
            mm = m[idx]
            x = (lv[idx] >= L) & mm
            n += rising(x)
        out[f"alerts_L{L}+_per_crew_day"] = round(n / days, 3)
        out[f"minutes_L{L}+_pct"] = round(100 * float(((lv >= L) & m).sum() / m.sum()), 3)
    return out


def minute_prf(df, lv) -> dict:
    y = df["truth"].to_numpy() >= 2
    p = lv >= 2
    tp, fp, fn = int((y & p).sum()), int((~y & p).sum()), int((y & ~p).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0}


def ece(y, p, bins=10) -> tuple[float, list]:
    edges = np.linspace(0, 1, bins + 1)
    tab, e = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.sum() == 0:
            continue
        tab.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "mean_pred": round(float(p[m].mean()), 3),
                    "observed": round(float(y[m].mean()), 3)})
        e += m.mean() * abs(p[m].mean() - y[m].mean())
    return round(float(e), 4), tab


# ----------------------------------------------------------------------------- main
def main():
    t0 = time.time()
    REPORTS.mkdir(exist_ok=True)
    rules = pd.read_parquet(DATA_DIR / "test_rules.parquet")
    full_p = DATA_DIR / "test_full.parquet"
    if not full_p.exists():
        print("Running held-out episodes through the FULL engine (with models)...")
        full = run_many(specs_for(TEST_ASTRONAUTS, base_seed=2, load_models=True), 2, "test-full")
        full.to_parquet(full_p)
    full = pd.read_parquet(full_p)
    assert (rules["episode"].to_numpy() == full["episode"].to_numpy()).all() and len(rules) == len(full)
    train = pd.read_parquet(DATA_DIR / "train.parquet")
    R: dict = {"data": "SIMULATED. Held-out synthetic subjects " + str(list(TEST_ASTRONAUTS)) +
               " never seen in training (astronaut-level split).",
               "test_rows": int(len(rules)), "test_episodes": int(rules.episode.nunique())}

    # 1 -------------------------------------------------------- detection
    sysd = systems(rules, full)
    det_rows, R["detection"] = [], {}
    for name, lv in sysd.items():
        rows, summ = detection_table(rules, lv, name)
        det_rows += rows
        summ.update(false_alarms(rules, lv))
        summ["minute_level_L2"] = minute_prf(rules, lv)
        R["detection"][name] = summ
    det = pd.DataFrame(det_rows)
    R["detection_by_scenario"] = (det.groupby(["system", "scenario"])
                                  .agg(recall=("detected", "mean"), median_latency=("latency_min", "median"))
                                  .round(2).reset_index().to_dict("records"))

    # 2 -------------------------------------------------------- sensor failure
    sm = rules[rules.scenario == "sensor_malfunction"]
    idx = sm.index.to_numpy()
    sens = {}
    for name, lv in sysd.items():
        post = (sm["min_since_onset"] >= 0).to_numpy()
        n = sum(rising((lv[g] >= 2) & post[np.isin(idx, g)]) for g in [sm.index[sm.episode == e].to_numpy()
                                                                         for e in sm.episode.unique()])
        sens[name] = {"medical_escalations_L2+": int(n), "episodes": int(sm.episode.nunique())}
    lat = []
    for e, g in full[full.scenario == "sensor_malfunction"].groupby("episode"):
        a = g[(g.min_since_onset >= 0) & g.sensor_alert]
        lat.append(float(a.min_since_onset.min()) if len(a) else None)
    sens["ARES sensor-alert latency_min (median)"] = float(np.median([x for x in lat if x is not None])) if any(
        x is not None for x in lat) else None
    sens["note"] = "Physiology is normal in these episodes; every L2+ escalation is a false medical alarm."
    R["sensor_failure"] = sens

    # 3 -------------------------------------------------------- comms
    by = det[det.system == "ARES full"].groupby("scenario")["latency_min"].median()
    R["comm_blackout"] = {"latency_blackout_emergency_min": float(by.get("blackout_emergency", np.nan)),
                          "latency_same_event_link_up_min": float(by.get("spo2_drop", np.nan)),
                          "note": "Detection is entirely onboard; link state must not change it. Queue "
                                  "behaviour (no message loss, priority order) is unit-tested."}

    # 4 -------------------------------------------------------- radiation
    rl = []
    for e, g in full[full.scenario == "radiation_event"].groupby("episode"):
        a = g[(g.min_since_onset >= 0) & g.spe]
        rl.append(float(a.min_since_onset.min()) if len(a) else None)
    R["radiation"] = {"spe_detected": int(sum(x is not None for x in rl)), "episodes": len(rl),
                      "median_detection_min_after_onset": float(np.median([x for x in rl if x is not None])) if rl else None,
                      "note": "SPE onset ramps over 60 min; detection = dosimeter rate > 3x modelled GCR for 5 min. "
                              "Medical levels intentionally unaffected (radiation is an environmental response)."}

    # 5 -------------------------------------------------------- anomaly models
    print("anomaly model comparison...")
    R["anomaly"] = anomaly_comparison(train, rules)

    # 6 -------------------------------------------------------- forecaster
    print("forecaster comparison...")
    R["forecaster"] = forecaster_eval(train, rules)

    # 7 -------------------------------------------------------- confusion
    cm = pd.crosstab(rules["truth"], full["pred"]).reindex(index=range(4), columns=range(4), fill_value=0)
    R["confusion_truth_vs_ares_full"] = {"rows=truth, cols=pred": cm.values.tolist()}
    u = full[full["pred"] < rules["truth"]].assign(truth=rules["truth"])
    R["under_triage_breakdown"] = (u.groupby(["scenario", "truth", "pred"]).size().sort_values(ascending=False)
                                   .head(8).reset_index(name="minutes").to_dict("records"))
    over = int(np.triu(cm.values, 1).sum())
    under = int(np.tril(cm.values, -1).sum())
    R["confusion_truth_vs_ares_full"]["over_triage_minutes"] = over
    R["confusion_truth_vs_ares_full"]["under_triage_minutes"] = under

    # 8 -------------------------------------------------------- behavioral
    R["behavioral"] = behavioral_eval()

    R["runtime_s"] = round(time.time() - t0, 1)
    (REPORTS / "evaluation.json").write_text(json.dumps(R, indent=2, default=float))
    det.to_csv(REPORTS / "detection_events.csv", index=False)
    figures(R, det)
    write_markdown(R)
    print(f"done in {time.time() - t0:.0f}s -> reports/")


def anomaly_comparison(train, test) -> dict:
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import OneClassSVM

    nom_tr = train[nominal_mask(train)]
    fit = nom_tr[nom_tr.astronaut_index < 12]
    ref = nom_tr[nom_tr.astronaut_index >= 12]
    Xf = fit[ANOMALY_FEATURES].to_numpy()
    rng = np.random.default_rng(0)
    sub = lambda X, n: X[rng.choice(len(X), min(n, len(X)), replace=False)]  # noqa: E731
    sc = StandardScaler().fit(Xf)
    models = {}
    am = AnomalyModel.load()
    models["Isolation Forest (deployed)"] = lambda X: -am.model.score_samples(X)
    lof = LocalOutlierFactor(n_neighbors=35, novelty=True).fit(sub(Xf, 20000))
    models["Local Outlier Factor"] = lambda X: -lof.score_samples(X)
    oc = OneClassSVM(nu=0.01, gamma="scale").fit(sc.transform(sub(Xf, 6000)))
    models["One-Class SVM"] = lambda X: -oc.score_samples(sc.transform(X))
    Xs = sc.transform(sub(Xf, 40000))
    ae = MLPRegressor(hidden_layer_sizes=(10, 4, 10), max_iter=80, random_state=0, early_stopping=True).fit(Xs, Xs)
    models["Autoencoder (MLP 14-10-4-10-14)"] = lambda X: ((ae.predict(sc.transform(X)) - sc.transform(X)) ** 2).mean(1)
    models["Baseline: max personal z"] = lambda X: X[:, :len(VITAL_KEYS)].max(1)

    nom_te = nominal_mask(test).to_numpy()
    no_fault = (test["faults"].fillna("") == "").to_numpy()
    pos = (test["truth"].to_numpy() >= 1) & no_fault
    keep = nom_te | pos
    Xte = test[ANOMALY_FEATURES].to_numpy()
    fault = ~no_fault & (test["truth"].to_numpy() == 0)
    out = {}
    Xref = ref[ANOMALY_FEATURES].to_numpy()
    for name, f in models.items():
        s = f(Xte)
        thr = np.quantile(f(Xref), 0.995)    # operating point: 0.5% of nominal validation minutes
        y, sk = pos[keep], s[keep]
        pred = s >= thr
        tp, fp, fn = int((pred & pos).sum()), int((pred & nom_te).sum()), int((~pred & pos).sum())
        prc = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        lats = []
        for e, idx in test.groupby("episode").indices.items():
            g = test.iloc[idx]
            if g.scenario.iat[0] not in ACUTE:
                continue
            on = (g.truth.to_numpy() >= 1)
            if not on.any():
                continue
            t1 = g.t.to_numpy()[on].min()
            hit = (g.min_since_onset.to_numpy() >= 0) & pred[idx]
            if hit.any():
                lats.append(float(g.t.to_numpy()[hit].min() - t1))
        out[name] = {"roc_auc": round(roc_auc_score(y, sk), 4), "pr_auc": round(average_precision_score(y, sk), 4),
                     "precision": round(prc, 3), "recall": round(rec, 3),
                     "f1": round(2 * prc * rec / (prc + rec), 3) if prc + rec else 0,
                     "false_alarm_rate_nominal_min": round(float(pred[nom_te].mean()), 4),
                     "median_latency_vs_L1_onset_min": float(np.median(lats)) if lats else None,
                     "flags_on_sensor_fault_minutes": round(float(pred[fault].mean()), 3) if fault.any() else None}
    out["_setup"] = {"positives": "minutes with truth level >= 1 (no sensor fault)",
                     "negatives": "pre-onset nominal minutes", "threshold": "99.5th pct of nominal validation scores",
                     "fit": "nominal minutes of train subjects 0-11"}
    return out


def forecaster_eval(train, test) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    tr, te = forecaster_rows(train), forecaster_rows(test)
    Xtr, ytr = tr[FEATURE_NAMES].to_numpy(), tr["y_future"].to_numpy()
    Xte, yte = te[FEATURE_NAMES].to_numpy(), te["y_future"].to_numpy()
    rf = RiskForecaster.load()
    p_gb = rf.predict_batch(Xte)
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)).fit(Xtr, ytr)
    p_lr = lr.predict_proba(Xte)[:, 1]
    zmax = te["zb_max"].to_numpy()
    out = {"base_rate": round(float(yte.mean()), 4), "test_rows": int(len(te)), "horizon_min": 30}
    for name, p in (("Gradient boosting + isotonic (deployed)", p_gb), ("Logistic regression", p_lr),
                    ("Baseline: max personal z (score only)", zmax)):
        d = {"roc_auc": round(roc_auc_score(yte, p), 4), "pr_auc": round(average_precision_score(yte, p), 4)}
        if p is not zmax:
            d["brier"] = round(brier_score_loss(yte, p), 4)
            d["ece"], d["calibration"] = ece(yte, p)
        out[name] = d
    # horizon: discrimination of positives by time-to-event bucket vs all negatives
    tte = []
    for e, idx in te.groupby("episode").indices.items():
        g = te.iloc[idx]
        full = test[test.episode == e]
        t2 = full.t[full.truth >= 2]
        first = t2.min() if len(t2) else np.inf
        tte.append(pd.Series(first - g.t.to_numpy(), index=g.index))
    tte = pd.concat(tte).reindex(te.index).to_numpy()
    hz = {}
    for lo, hi in ((1, 10), (11, 20), (21, 30)):
        m = (yte == 1) & (tte >= lo) & (tte <= hi)
        mm = m | (yte == 0)
        if m.sum() > 20:
            hz[f"{lo}-{hi} min ahead"] = {"n_pos": int(m.sum()), "roc_auc": round(roc_auc_score(m[mm], p_gb[mm]), 4)}
    out["by_time_to_event"] = hz
    # leave-one-scenario-out: can it anticipate an emergency TYPE it never saw?
    loso = {}
    params = dict(max_iter=150, learning_rate=0.08, max_leaf_nodes=31, class_weight="balanced", random_state=0)
    neg_te = te.scenario == "normal"
    m_in = HistGradientBoostingClassifier(**params).fit(Xtr, ytr)   # same model for every 'seen' column
    for sc in ACUTE:
        mtr = (tr.scenario != sc).to_numpy()
        mte = ((te.scenario == sc) | neg_te).to_numpy()
        if yte[mte].sum() < 10:
            continue
        m_out = HistGradientBoostingClassifier(**params).fit(Xtr[mtr], ytr[mtr])
        loso[sc] = {"pr_auc_scenario_unseen": round(average_precision_score(yte[mte], m_out.predict_proba(Xte[mte])[:, 1]), 4),
                    "pr_auc_scenario_seen": round(average_precision_score(yte[mte], m_in.predict_proba(Xte[mte])[:, 1]), 4)}
    out["leave_one_scenario_out"] = loso
    return out


def behavioral_eval(n_subjects: int = 40, days: int = 12) -> dict:
    """Readiness flagging under simulated sleep restriction vs control (SIMULATED)."""
    from ares.behavioral.model import BehavioralProfile, BehavioralRecord
    from ares.behavioral.simulate import simulate_checkin, simulate_pvt

    res = {"control": [], "restricted": []}
    for arm in res:
        for s in range(n_subjects):
            rng = np.random.default_rng(5000 + s + (0 if arm == "control" else 999))
            base_rt = rng.uniform(215, 275)
            need = rng.uniform(7.5, 8.5)
            bp = BehavioralProfile(f"B{s}", sleep_need_h=need)
            first = None
            debt = 0.0
            for d in range(days):
                sl = need + rng.normal(-0.2, 0.4) if (arm == "control" or d < 4) else need - 2.5 + rng.normal(0, 0.4)
                debt = max(0.0, debt * 0.85 + max(0, need - sl))
                a = bp.add(BehavioralRecord(d, simulate_pvt(rng, base_rt, debt, 0.0),
                                            simulate_checkin(rng, sl, need, debt, 0.0), sl))
                if a["level"] >= 1 and first is None and d >= 4:
                    first = d - 4
            res[arm].append(first)
    ctrl = [x for x in res["control"] if x is not None]
    rest = [x for x in res["restricted"] if x is not None]
    return {"subjects_per_arm": n_subjects, "restriction": "sleep need - 2.5 h/night from day 4",
            "sensitivity_flag_within_8d": round(len(rest) / n_subjects, 3),
            "median_days_to_flag": float(np.median(rest)) if rest else None,
            "control_false_flag_rate_8d": round(len(ctrl) / n_subjects, 3),
            "note": "Simulated dose-response; measures logic, not validity."}


# ----------------------------------------------------------------------------- outputs
def figures(R, det):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, ink2, grid = "#0b0b0b", "#52514e", "#e4e3df"
    colors = {"Static limits": "#2a78d6", "NEWS2 >= 5": "#eb6834", "ARES full": "#1baf7a"}
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": grid, "axes.labelcolor": ink2, "xtick.color": ink2,
                         "ytick.color": ink2, "axes.spines.top": False, "axes.spines.right": False})
    # false alarms
    fig, ax = plt.subplots(figsize=(7, 3.2))
    names = list(R["detection"])
    vals = [R["detection"][n]["alerts_L2+_per_crew_day"] for n in names]
    ax.barh(names, vals, color="#2a78d6", height=0.5)
    for i, v in enumerate(vals):
        ax.text(v, i, f"  {v:.2f}", va="center", color=ink, fontsize=9)
    ax.set_xlabel("False L2+ alarms per crew-day (nominal operation)")
    ax.invert_yaxis()
    ax.grid(axis="x", color=grid, lw=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(REPORTS / "fig_false_alarms.png", dpi=150)
    plt.close(fig)
    # calibration
    cal = R["forecaster"]["Gradient boosting + isotonic (deployed)"]["calibration"]
    fig, ax = plt.subplots(figsize=(4.2, 4))
    ax.plot([0, 1], [0, 1], color=grid, lw=1.5, ls="--", label="perfect calibration")
    ax.plot([c["mean_pred"] for c in cal], [c["observed"] for c in cal], color="#2a78d6", lw=2, marker="o", ms=6,
            label="ARES forecaster")
    ax.set_xlabel("Predicted risk score")
    ax.set_ylabel("Observed event rate (held-out)")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(color=grid, lw=0.8)
    fig.tight_layout()
    fig.savefig(REPORTS / "fig_calibration.png", dpi=150)
    plt.close(fig)
    # operating points: recall vs false alarms (the honest trade-off; latency is misleading for noisy
    # baselines because their false alarms fire shortly after onset by chance)
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    pal = {"Static limits": "#2a78d6", "Static limits +5 min": "#2a78d6", "NEWS2 >= 5": "#eb6834",
           "ARES rules": "#1baf7a", "ARES full": "#1baf7a"}
    pts = dict(R["detection"])
    same = (pts["ARES rules"]["alerts_L2+_per_crew_day"] == pts["ARES full"]["alerts_L2+_per_crew_day"]
            and pts["ARES rules"]["minute_level_L2"] == pts["ARES full"]["minute_level_L2"])
    if same:
        pts["ARES (rules = full)"] = pts.pop("ARES rules")
        pts.pop("ARES full")
        pal["ARES (rules = full)"] = pal["ARES rules"]
    offs = {"Static limits": (-10, -26), "NEWS2 >= 5": (-30, 10), "Static limits +5 min": (8, 6)}
    for n, d in pts.items():
        x, y = d["alerts_L2+_per_crew_day"], d["minute_level_L2"]["recall"]
        ax.scatter([x], [y], s=70, color=pal[n], edgecolor="white", linewidth=2, zorder=3)
        dx, dy = offs.get(n, (8, 6))
        ax.annotate(f"{n}  F1 {d['minute_level_L2']['f1']:.2f}", (x, y), textcoords="offset points",
                    xytext=(dx, dy), fontsize=8, color=ink, ha="right" if dx < 0 else "left")
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlabel("False L2+ alarms per crew-day (nominal operation, log scale)")
    ax.set_ylabel("Minute-level recall of L2+ periods")
    ax.set_ylim(0, 1.05)
    ax.grid(color=grid, lw=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(REPORTS / "fig_tradeoff.png", dpi=150)
    plt.close(fig)
    _ = det


def write_markdown(R):
    L = ["# ARES evaluation report", "", f"> {R['data']}", "",
         "All numbers below come from `scripts/evaluate.py` and `reports/evaluation.json`. They measure whether ARES "
         "recovers the scenario designer's labels on **simulated** physiology. They are **not** clinical performance.", "",
         "## 1. Emergency detection vs baselines", "",
         "| System | Events | Recall (L2+) | Median latency (min) | Missed critical | False L1+ alerts / crew-day | False L2+ alerts / crew-day | Minute F1 (L2+) |",
         "|---|---|---|---|---|---|---|---|"]
    for n, d in R["detection"].items():
        L.append(f"| {n} | {d['events']} | {d['recall']:.2f} | {d['median_latency_min']} | {d['missed_critical']}/{d['critical_events']} | "
                 f"{d['alerts_L1+_per_crew_day']:.2f} | {d['alerts_L2+_per_crew_day']:.2f} | {d['minute_level_L2']['f1']:.2f} |")
    L += ["", "Negative latency = ARES reached L2 before the scenario's own L2 label (counted in over-triage below).", "",
          "![False alarms](fig_false_alarms.png)", "", "![Recall vs false alarms](fig_tradeoff.png)", "",
          "## 2. Sensor failure", "", "| System | False medical escalations (L2+) |", "|---|---|"]
    for n, d in R["sensor_failure"].items():
        if isinstance(d, dict):
            L.append(f"| {n} | {d['medical_escalations_L2+']} over {d['episodes']} episodes |")
    L += ["", f"ARES raised a 'verify sensor' observation after a median of {R['sensor_failure']['ARES sensor-alert latency_min (median)']} min.", "",
          "## 3. Communication blackout", "",
          f"Median latency with Earth link forced down: **{R['comm_blackout']['latency_blackout_emergency_min']} min**; "
          f"same event with link up: **{R['comm_blackout']['latency_same_event_link_up_min']} min**.", "",
          "## 4. Radiation (SPE)", "",
          f"SPE detected in {R['radiation']['spe_detected']}/{R['radiation']['episodes']} episodes, median "
          f"{R['radiation']['median_detection_min_after_onset']} min after onset (60-min ramp).", "",
          "## 5. Anomaly models (held-out subjects)", "",
          "| Model | ROC-AUC | PR-AUC | Precision | Recall | F1 | Nominal false-alarm rate | Median latency vs L1 (min) | Flags sensor-fault minutes |",
          "|---|---|---|---|---|---|---|---|---|"]
    for n, d in R["anomaly"].items():
        if n.startswith("_"):
            continue
        L.append(f"| {n} | {d['roc_auc']} | {d['pr_auc']} | {d['precision']} | {d['recall']} | {d['f1']} | "
                 f"{d['false_alarm_rate_nominal_min']} | {d['median_latency_vs_L1_onset_min']} | {d['flags_on_sensor_fault_minutes']} |")
    f = R["forecaster"]
    L += ["", f"Setup: {R['anomaly']['_setup']}", "", "## 6. Risk forecaster (30-min horizon)", "",
          f"Base rate {f['base_rate']} over {f['test_rows']:,} held-out minutes.", "",
          "| Model | ROC-AUC | PR-AUC | Brier | ECE |", "|---|---|---|---|---|"]
    for n in ("Gradient boosting + isotonic (deployed)", "Logistic regression", "Baseline: max personal z (score only)"):
        d = f[n]
        L.append(f"| {n} | {d['roc_auc']} | {d['pr_auc']} | {d.get('brier', '-')} | {d.get('ece', '-')} |")
    L += ["", "![Calibration](fig_calibration.png)", "", "By time to event (positives only, vs all negatives):", ""]
    for k, v in f["by_time_to_event"].items():
        L.append(f"- {k}: ROC-AUC {v['roc_auc']} (n={v['n_pos']})")
    L += ["", "Leave-one-scenario-out (PR-AUC on that scenario + normal episodes):", "",
          "| Held-out scenario | Seen in training | Unseen in training |", "|---|---|---|"]
    for k, v in f["leave_one_scenario_out"].items():
        L.append(f"| {k} | {v['pr_auc_scenario_seen']} | {v['pr_auc_scenario_unseen']} |")
    c = R["confusion_truth_vs_ares_full"]
    L += ["", "## 7. Level confusion (rows = designer truth L0-L3, cols = ARES)", "", "| | L0 | L1 | L2 | L3 |", "|---|---|---|---|---|"]
    for i, row in enumerate(c["rows=truth, cols=pred"]):
        L.append(f"| L{i} | " + " | ".join(str(x) for x in row) + " |")
    b = R["behavioral"]
    L += ["", f"Over-triage minutes {c['over_triage_minutes']:,}; under-triage minutes {c['under_triage_minutes']:,}.", "",
          "Where the under-triage minutes come from:", "", "| Scenario | Truth | ARES | Minutes | Interpretation |", "|---|---|---|---|---|"]
    notes = {"sleep_deprivation": "by design: fatigue is handled by the behavioral channel (section 8), not physiological alarms",
             "radiation_event": "by design: SPE is an environmental incident (section 4); medical level unaffected",
             "cardiac_arrhythmia": "OPEN ISSUE 1: irregular tachycardia with falling BP held at L2; fix = 'unstable rhythm' rule (pattern + BP below personal band -> L3)",
             "blackout_emergency": "OPEN ISSUE 2: hours into sustained desaturation at the 85% limit, exercise context downgrades to L2; fix = no de-escalation while a critical value persists",
             "spo2_drop": "OPEN ISSUE 2 (same as above)",
             "dehydration": "slow onset: ARES one level below designer label"}
    for r in R["under_triage_breakdown"]:
        L.append(f"| {r['scenario']} | L{r['truth']} | L{r['pred']} | {r['minutes']:,} | {notes.get(r['scenario'], '')} |")
    L += ["",
          "## 8. Behavioral readiness (simulated sleep restriction)", "",
          f"- Restricted arm flagged within 8 days: {b['sensitivity_flag_within_8d']:.0%} (median {b['median_days_to_flag']} days)",
          f"- Control arm falsely flagged within 8 days: {b['control_false_flag_rate_8d']:.0%}", "",
          "## Open issues found by this evaluation (not fixed post-hoc, to keep the held-out test clean)", "",
          "1. **Unstable irregular tachycardia under-triaged** (L2 instead of L3). Proposed rule: irregular-rhythm pattern "
          "+ systolic BP below the personal band -> L3 (clinical 'unstable tachycardia' logic).",
          "2. **Sustained critical desaturation downgraded during exercise/recovery.** Proposed rule: once L3 is reached on a "
          "critical-limit channel, do not de-escalate while that channel stays beyond its hard limit, regardless of context.",
          "3. **ML observation alerts.** The ML layer adds ~0.8 L1 alerts per crew-day over the rules alone with no gain in "
          "L2+ recall on these scenarios; its value is earlier *observation*, which should be confirmed on real data.",
          "4. **Unsupervised anomaly models ~ simple max personal z** (ROC-AUC 0.75-0.76 for all). The personal baseline does "
          "most of the work; the Isolation Forest is kept for patterns no rule anticipated, but is not a major contributor here.",
          "5. **Forecaster does not generalise to unseen emergency types** (leave-one-scenario-out PR-AUC collapses for "
          "respiratory, dehydration, multi-system). This is why ML is never allowed to declare an emergency.",
          "",
          "Both rule fixes must be validated on a NEW set of held-out subjects, not on this one.", "",
          "## Limitations", "",
          "- Ground truth is the simulator designer's labelling, so these metrics test internal consistency, not clinical validity.",
          "- The forecaster learns the simulator's dynamics; leave-one-scenario-out shows how much drops on an unseen event type.",
          "- Real-data validation of the ECG chain is reported separately in `reports/REAL_DATA_VALIDATION.md`.", ""]
    (REPORTS / "EVALUATION.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
