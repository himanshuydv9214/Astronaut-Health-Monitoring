"""CSV and PDF exports of saved tests (fully offline; PDF via matplotlib, already a project dependency)."""

from __future__ import annotations

import csv
import io
import time

LABELS = [("mean_rt_ms", "Average reaction time", "ms"), ("median_rt_ms", "Median reaction time", "ms"),
          ("fastest_ms", "Fastest response", "ms"), ("slowest_ms", "Slowest response", "ms"),
          ("sd_ms", "Response-time variability (SD)", "ms"), ("cv", "Coefficient of variation", ""),
          ("response_speed", "Mean response speed (PVT-B primary outcome)", "1/s"),
          ("lapses", "Lapses (>= 355 ms or missed)", ""), ("misses", "Missed (no response in 10 s)", ""),
          ("false_starts", "False starts (< 130 ms)", ""), ("premature_no_stimulus", "Presses with no stimulus", ""),
          ("trials", "Stimuli presented", ""), ("responses", "Valid responses", "")]


def _t(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""


def _rows_for_metrics(test: dict) -> list[tuple[str, str]]:
    m = (test.get("result") or {}).get("metrics") or {}
    if test["test_type"] == "pvt":
        return [(lab + (f" ({u})" if u else ""), "" if m.get(k) is None else str(m.get(k))) for k, lab, u in LABELS]
    return [(k.replace("_", " "), ", ".join(map(str, v)) if isinstance(v, list) else
             "; ".join(f"{a}={b}" for a, b in v.items()) if isinstance(v, dict) else str(v)) for k, v in m.items()]


def test_csv(test: dict) -> str:
    b = io.StringIO()
    w = csv.writer(b)
    w.writerow(["ARES test report - research prototype, not a medical device"])
    for k, v in (("Test ID", test["test_id"]), ("Astronaut", f"{test['astronaut_name']} ({test['astronaut_id']})"),
                 ("Test", test["test_name"]), ("Type", test["test_type"]), ("Status", test["status"]),
                 ("Started", _t(test["started_at"])), ("Completed", _t(test["completed_at"])),
                 ("Duration (s)", test["duration_s"]), ("Mission day", test["mission_day"]),
                 ("Data source", test["data_source"]), ("App session", test["app_session"]),
                 ("Configuration", "; ".join(f"{a}={c}" for a, c in (test.get("config") or {}).items()))):
        w.writerow([k, "" if v is None else v])
    w.writerow([])
    w.writerow(["Metric", "Value"])
    for row in _rows_for_metrics(test):
        w.writerow(row)
    res = test.get("result") or {}
    cmp_ = res.get("comparison") or {}
    for name in ("baseline", "previous"):
        c = cmp_.get(name)
        if c:
            w.writerow([])
            w.writerow([f"Comparison with {name}", "current", "reference", "difference"])
            for k, v in c.items():
                if v:
                    w.writerow([k, v["current"], v["reference"], v["difference"]])
    if res.get("interpretation"):
        w.writerow([])
        w.writerow(["Interpretation (observed differences, not a diagnosis)"])
        for x in res["interpretation"]:
            w.writerow([x["text"]])
    if test.get("trials"):
        w.writerow([])
        w.writerow(["trial", "outcome", "reaction_time_ms", "interstimulus_interval_ms", "time_from_start_ms"])
        for t in test["trials"]:
            w.writerow([t["trial_no"], t["outcome"], "" if t["rt_ms"] is None else t["rt_ms"],
                        "" if t["isi_ms"] is None else round(t["isi_ms"]),
                        "" if t["t_offset_ms"] is None else round(t["t_offset_ms"])])
    return b.getvalue()


def list_csv(rows: list[dict]) -> str:
    b = io.StringIO()
    w = csv.writer(b)
    w.writerow(["test_id", "date", "astronaut_id", "astronaut", "test", "status", "duration_s", "mission_day",
                "result", "trials", "data_source"])
    for r in rows:
        w.writerow([r["test_id"], _t(r["started_at"]), r["astronaut_id"], r["astronaut_name"], r["test_name"],
                    r["status"], r["duration_s"], r["mission_day"], r["summary"], r["trials"], r["data_source"]])
    return b.getvalue()


def test_pdf(test: dict, trend: dict | None = None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    res = test.get("result") or {}
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))          # A4 portrait
        fig.text(0.07, 0.955, "ARES - test report", fontsize=18, weight="bold")
        fig.text(0.07, 0.935, "Research prototype. Not a medical device; one test is never a diagnosis.", fontsize=8,
                 color="#a05a00")
        info = [("Test", test["test_name"]), ("Test ID", test["test_id"]),
                ("Astronaut", f"{test['astronaut_name']} ({test['astronaut_id']})"), ("Status", test["status"]),
                ("Started", _t(test["started_at"])), ("Completed", _t(test["completed_at"])),
                ("Duration", f"{test['duration_s']:.0f} s" if test["duration_s"] else "-"),
                ("Mission day", test["mission_day"]), ("Data source", test["data_source"])]
        y = 0.9
        for k, v in info:
            fig.text(0.07, y, k, fontsize=9, color="#555")
            fig.text(0.3, y, "-" if v is None else str(v), fontsize=9)
            y -= 0.018
        y -= 0.01
        fig.text(0.07, y, "Results", fontsize=12, weight="bold")
        y -= 0.022
        for k, v in _rows_for_metrics(test):
            fig.text(0.07, y, k, fontsize=8.5)
            fig.text(0.62, y, v or "-", fontsize=8.5)
            y -= 0.016
        if res.get("interpretation"):
            y -= 0.01
            fig.text(0.07, y, "What this means (observed differences)", fontsize=12, weight="bold")
            y -= 0.02
            import textwrap
            for x in res["interpretation"]:
                for i, line in enumerate(textwrap.wrap(x["text"], 105)):
                    fig.text(0.07, y, ("- " if i == 0 else "  ") + line, fontsize=8.5)
                    y -= 0.015
        trials = test.get("trials") or []
        rts = [(t["trial_no"], t["rt_ms"], t["outcome"]) for t in trials if t["rt_ms"] is not None]
        if rts and y > 0.3:
            ax = fig.add_axes([0.1, 0.06, 0.82, min(0.22, y - 0.1)])
            col = {"response": "#1f8fbf", "lapse": "#d4a017", "false_start": "#c0392b"}
            ax.bar([r[0] for r in rts], [r[1] for r in rts], color=[col.get(r[2], "#888") for r in rts])
            ax.axhline(355, ls=":", color="#d4a017", lw=1)
            ax.set_xlabel("trial")
            ax.set_ylabel("reaction time (ms)")
            ax.set_title("Individual trials (dotted line = 355 ms lapse threshold)", fontsize=9)
        pdf.savefig(fig)
        plt.close(fig)
        if trend and trend.get("series"):
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.text(0.07, 0.955, f"Reaction-test history - {test['astronaut_name']}", fontsize=15, weight="bold")
            s = trend["series"]
            ax = fig.add_axes([0.1, 0.62, 0.82, 0.28])
            ax.plot(range(1, len(s) + 1), [x["mean_rt_ms"] for x in s], "o-", color="#1f8fbf", label="average")
            ax.plot(range(1, len(s) + 1), [x["median_rt_ms"] for x in s], "s--", color="#555", label="median")
            b = (trend.get("baseline") or {}).get("values") or {}
            if b.get("mean_rt_ms"):
                ax.axhline(b["mean_rt_ms"], color="#2a9d8f", ls=":", label="personal baseline")
            ax.set_xlabel("saved completed test #")
            ax.set_ylabel("ms")
            ax.legend(fontsize=8)
            ax2 = fig.add_axes([0.1, 0.3, 0.82, 0.22])
            ax2.bar(range(1, len(s) + 1), [x["lapses"] or 0 for x in s], color="#d4a017")
            ax2.set_ylabel("lapses")
            ax2.set_xlabel("saved completed test #")
            y = 0.24
            fig.text(0.07, y, "Observed trends", fontsize=12, weight="bold")
            for o in trend.get("observed", []):
                y -= 0.02
                fig.text(0.07, y, "- " + o["text"], fontsize=8.5)
            y -= 0.03
            fig.text(0.07, y, trend["note"][:150], fontsize=7.5, color="#555")
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()
