import { useState } from "react";
import { useApp } from "../App";
import { ago, CONTEXT, fmt, relT, STATE_COLOR, usePoll, VITALS } from "../api";
import { LevelPill, Panel, Plot, PLOT_LAYOUT, Spark, Status } from "../ui";

const STATUS_TEXT: Record<string, string> = { stable: "Stable", watch: "Watch", gradual: "Gradual change", sudden: "Sudden change — see alerts", insufficient: "Not enough data" };
const STATUS_CLASS: Record<string, string> = { stable: "stable", watch: "watch", gradual: "gradual", sudden: "sudden", insufficient: "insufficient" };
const dp = (k: string) => (k === "temp" ? 2 : k === "spo2" || k === "rr" ? 1 : 0);

function VitalCharts() {
  const { s } = useApp();
  const det = s.detail, r = det.recent, x0 = s.t - s.demo_minute;
  const x = r.t.map((t: number) => (t - x0) / 60);
  return (
    <div className="grid g3">
      {VITALS.map(([k, lab, u, d]) => {
        const tr: any[] = [
          { x, y: r.hi[k], mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
          { x, y: r.lo[k], mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(63,216,255,.10)", hoverinfo: "skip" },
          { x, y: r.e[k], mode: "lines", line: { color: "#5f7da6", width: 1, dash: "dot" }, hovertemplate: "usual %{y:.1f}<extra></extra>" },
          { x, y: r.v[k], mode: "lines", line: { color: "#3fd8ff", width: 2 }, connectgaps: k === "sbp", hovertemplate: `${lab} %{y:.${d}f} ${u}<extra></extra>` },
        ];
        if (k === "sbp") tr.push({ x, y: r.v.dbp, mode: "lines", line: { color: "#3b82ff", width: 2 }, connectgaps: true, hovertemplate: "diastolic %{y:.0f}<extra></extra>" });
        return <Panel key={k} title={`${lab} · ${u}`} info="vitals"><Plot className="plot xs" data={tr}
          layout={PLOT_LAYOUT({ margin: { l: 36, r: 6, t: 2, b: 20 }, xaxis: { gridcolor: "rgba(110,170,255,.08)", ticksuffix: " h" } })} /></Panel>;
      })}
    </div>
  );
}

export function TrendTables({ aid }: { aid: string }) {
  const { s } = useApp();
  const { data } = usePoll<any>(aid ? `/api/health/history?astronaut=${aid}` : null, 5000);
  const [sel, setSel] = useState<string | null>(null);
  if (!data) return <div className="loading">Loading health history…</div>;
  const rows = data.rows as any[];
  const row = rows.find((r) => r.key === sel);
  const t0 = s.t - s.demo_minute;
  return (
    <>
      <Panel title="Health changes over time" info="longitudinal" right={<span className="muted" style={{ fontSize: 12 }}>Resting readings only · click a row for its history</span>}>
        <div className="tbl-wrap">
          <table className="tbl">
            <colgroup><col style={{ width: "24%" }} /><col style={{ width: "11%" }} /><col style={{ width: "11%" }} /><col style={{ width: "14%" }} /><col style={{ width: "16%" }} /><col style={{ width: "11%" }} /><col style={{ width: "13%" }} /></colgroup>
            <thead><tr><th>Measurement</th><th className="r">Baseline</th><th className="r">Current</th><th className="r">Change</th><th className="c">Trend (hourly)</th><th className="r">Updated</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className={`click ${sel === r.key ? "sel" : ""}`} onClick={() => setSel(sel === r.key ? null : r.key)}>
                  <td>{r.label}<span className="sub">{r.unit} · {r.source}</span></td>
                  <td className="r">{fmt(r.baseline, dp(r.key))}</td>
                  <td className="r">{fmt(r.current, dp(r.key))}</td>
                  <td className="r">{r.change == null ? "—" : `${r.change >= 0 ? "+" : ""}${fmt(r.change, dp(r.key))}`}<span className="sub">{r.change_pct == null ? "" : `${r.change_pct >= 0 ? "+" : ""}${r.change_pct}%`}</span></td>
                  <td className="c">{r.series ? <Spark values={r.series.map((p: any) => p.mean)} lo={r.baseline - 2 * r.baseline_sd} hi={r.baseline + 2 * r.baseline_sd}
                    color={r.status === "stable" ? STATE_COLOR.normal : r.status === "sudden" ? STATE_COLOR.elevated : STATE_COLOR.observation} /> : "—"}</td>
                  <td className="r">{r.last_updated_min == null ? "—" : ago(s.t - r.last_updated_min)}</td>
                  <td><Status s={STATUS_CLASS[r.status]} text={STATUS_TEXT[r.status]} /></td>
                </tr>))}
            </tbody>
          </table>
        </div>
        {row?.series && (
          <div className="mt">
            <b>{row.label}</b> <span className="muted">— hourly resting average vs this astronaut's baseline ± 2 SD</span>
            <Plot className="plot sm" data={[
              { x: row.series.map((p: any) => (p.hour * 60 - t0) / 60), y: row.series.map(() => row.baseline + 2 * row.baseline_sd), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
              { x: row.series.map((p: any) => (p.hour * 60 - t0) / 60), y: row.series.map(() => row.baseline - 2 * row.baseline_sd), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(63,216,255,.10)", hoverinfo: "skip" },
              { x: row.series.map((p: any) => (p.hour * 60 - t0) / 60), y: row.series.map(() => row.baseline), mode: "lines", line: { color: "#5f7da6", dash: "dot", width: 1 }, hoverinfo: "skip" },
              { x: row.series.map((p: any) => (p.hour * 60 - t0) / 60), y: row.series.map((p: any) => p.mean), mode: "lines+markers", line: { color: "#3fd8ff", width: 2 }, marker: { size: 5 },
                text: row.series.map((p: any) => `${p.n} readings`), hovertemplate: `%{y:.2f} ${row.unit} (%{text})<extra></extra>` },
            ]} layout={PLOT_LAYOUT({ xaxis: { gridcolor: "rgba(110,170,255,.08)", ticksuffix: " h", title: { text: "mission hours since monitoring start", font: { size: 10 } } } })} />
          </div>)}
      </Panel>
      <Panel className="mt" title="Gradual changes from normal" info="drift"
        right={<span className="muted" style={{ fontSize: 12 }}>Drift builds over hours or days — it is not an emergency alarm</span>}>
        <div className="tbl-wrap">
          <table className="tbl">
            <colgroup><col style={{ width: "22%" }} /><col style={{ width: "14%" }} /><col style={{ width: "10%" }} /><col style={{ width: "12%" }} /><col style={{ width: "10%" }} /><col style={{ width: "9%" }} /><col style={{ width: "13%" }} /><col style={{ width: "10%" }} /></colgroup>
            <thead><tr><th>Measurement</th><th className="r">Personal baseline</th><th className="r">Current</th><th className="r">Size of change</th><th className="c">Direction</th><th className="r">Lasting</th><th>Status</th><th>Data quality</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td>{r.label}<span className="sub">{r.unit}</span></td>
                  <td className="r">{r.baseline == null ? "—" : `${fmt(r.baseline, dp(r.key))} ± ${fmt(r.baseline_sd, dp(r.key) + 1)}`}</td>
                  <td className="r">{fmt(r.current, dp(r.key))}</td>
                  <td className="r">{r.z == null ? "—" : `${Math.abs(r.z).toFixed(1)} × normal variation`}</td>
                  <td className="c">{r.direction === "up" ? "▲ rising" : r.direction === "down" ? "▼ falling" : "—"}</td>
                  <td className="r">{r.duration_h ? `${r.duration_h} h` : "—"}</td>
                  <td><Status s={STATUS_CLASS[r.status]} text={STATUS_TEXT[r.status]} /></td>
                  <td><Status s={r.quality === "good" ? "good" : r.quality === "limited" ? "limited" : "stale"} text={r.quality ?? "—"} /></td>
                </tr>))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>Reference: {data.reference}. A <b>sudden change</b> (minutes) is handled by the alert system; <b>gradual change</b> means a sustained shift of 2× normal variation for 3 hours or more.</p>
      </Panel>
    </>
  );
}

export default function Crew() {
  const { s, aid } = useApp();
  const det = s.detail, p = det.profile, cls = det.classification;
  const c = s.crew.find((x: any) => x.id === p.id);
  return (
    <>
      <div className="page-head"><div><h1>{p.name} <span className="muted" style={{ fontSize: 15, fontWeight: 400 }}>· {p.role}</span></h1>
        <p>Individual health profile: live readings against this astronaut's own normal ranges, changes over time and gradual drift. Fictional profile, age {p.age}. {p.history.join("; ")}.</p></div>
        <LevelPill level={cls.level} text={`Health risk level: ${["Normal", "Watch", "Medical check needed", "Emergency"][cls.level]}`} /></div>
      <div className="grid g4" style={{ marginBottom: 12 }}>
        <Panel title="Activity"><b style={{ fontSize: 16 }}>{CONTEXT[c.context] ?? c.context}</b><div className="muted">detected from motion sensor</div></Panel>
        <Panel title="Sensors"><Status s={c.sensor_health === "OK" ? "good" : "unknown"} text={c.sensor_health === "OK" ? "All sensors OK" : c.sensor_health} /><div className="muted">heart-rate source: {det.ecg?.hr_source ?? "—"}</div></Panel>
        <Panel title="Sleep (last 24 h)"><b className="num" style={{ fontSize: 16 }}>{fmt(c.sleep_h_24h, 1)} h</b><div className="muted">from wrist motion</div></Panel>
        <Panel title="Detection confidence"><b style={{ fontSize: 16 }}>{cls.confidence_label}</b> <span className="muted num">({cls.confidence})</span><div className="muted">how sure ARES is about the current level</div></Panel>
      </div>
      <VitalCharts />
      <div className="grid g2 mt">
        <Panel title="Heart rhythm (ECG)" info="ecg" right={<span className="muted" style={{ fontSize: 12 }}>{det.ecg?.proc ? `signal quality ${fmt(det.ecg.proc.quality, 2)} · ${det.ecg.proc.n_beats} beats` : ""}</span>}>
          {det.ecg ? <Plot className="plot sm" data={[{ x: det.ecg.mv.map((_: any, i: number) => i / (det.ecg.fs / 2)), y: det.ecg.mv, mode: "lines", line: { color: "#3fd8ff", width: 1.4 }, hovertemplate: "%{y:.2f} mV<extra></extra>" }]}
            layout={PLOT_LAYOUT({ xaxis: { gridcolor: "rgba(110,170,255,.08)", ticksuffix: " s" }, yaxis: { gridcolor: "rgba(110,170,255,.08)", ticksuffix: " mV" } })} /> : <div className="empty">No ECG.</div>}
        </Panel>
        <Panel title="This astronaut's normal ranges" info="baseline" right={<span className="muted" style={{ fontSize: 12 }}>for: {CONTEXT[c.context] ?? c.context}</span>}>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Measurement</th><th className="r">Usual</th><th className="r">Normal range</th><th className="r">Readings</th><th className="r">Trend/h</th><th>Type</th></tr></thead>
            <tbody>{Object.entries(det.baselines).map(([k, b]: any) => (
              <tr key={k}><td>{b.label}<span className="sub">{b.unit.replace("degC", "°C")}</span></td>
                <td className="r">{fmt(b.expected, 1)}</td><td className="r">{fmt(b.lo, 1)} – {fmt(b.hi, 1)}</td><td className="r">{b.n}</td>
                <td className="r">{fmt(det.slopes[k].slope_h, 2)}</td><td className="nowrap">{b.measured ? <span className="tag meas">measured</span> : <span className="tag meas derived">estimated</span>}</td></tr>))}</tbody>
          </table></div>
        </Panel>
      </div>
      <div className="mt"><TrendTables aid={aid!} /></div>
      <Panel className="mt" title="Health timeline">
        <div className="log">{det.timeline.length ? det.timeline.map((e: any, i: number) => (
          <div key={i} className={`logline l${e.level}`}><span className="t">{relT(e.t, s.t - s.demo_minute)}</span><span>{e.text}</span></div>)) : <div className="empty">No events yet.</div>}</div>
      </Panel>
    </>
  );
}
