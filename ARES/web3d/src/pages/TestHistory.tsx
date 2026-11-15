import { useEffect, useMemo, useState } from "react";
import { useApp } from "../App";
import { fmt, getJSON, usePoll } from "../api";
import { DataTag, Panel, Plot, PLOT_LAYOUT, Status } from "../ui";
import { STATUS_S, STATUS_TEXT } from "./Alertness";

/* Test History: every test performed in ARES, read from the local database (all sessions, survives restarts). */
const OUTCOME_COLOR: Record<string, string> = { response: "#3fd8ff", lapse: "#f2c94c", false_start: "#ff8a3d", miss: "#ff4d5e", premature: "#8090a8" };
const OUTCOME_TEXT: Record<string, string> = { response: "Response", lapse: "Lapse (≥ 355 ms)", false_start: "False start (< 130 ms)", miss: "Missed (no response in 10 s)", premature: "Press with no stimulus" };
const METRICS: [string, string, string, number][] = [
  ["mean_rt_ms", "Average", "ms", 0], ["median_rt_ms", "Median", "ms", 0], ["fastest_ms", "Fastest", "ms", 0], ["slowest_ms", "Slowest", "ms", 0],
  ["sd_ms", "Variability (SD)", "ms", 0], ["cv", "Coefficient of variation", "", 3], ["response_speed", "Response speed", "1/s", 2],
  ["lapses", "Lapses", "", 0], ["misses", "Missed", "", 0], ["false_starts", "False starts", "", 0], ["premature_no_stimulus", "Presses with no stimulus", "", 0],
  ["trials", "Stimuli", "", 0], ["responses", "Valid responses", "", 0],
];
const dt = (t: number | null | undefined) => (t ? new Date(t * 1000).toLocaleString() : "—");
const dur = (s: number | null | undefined) => (s == null ? "—" : s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`);
const ax = (t: string) => ({ gridcolor: "rgba(110,170,255,.08)", title: { text: t, font: { size: 10 } } });

function readId() { const q = location.hash.split("?")[1] ?? ""; return new URLSearchParams(q).get("id"); }

export default function TestHistory() {
  const { s } = useApp();
  const [f, setF] = useState({ astronaut: "", test_type: "", status: "", from: "", to: "" });
  const [sel, setSel] = useState<string | null>(readId());
  useEffect(() => { const h = () => setSel(readId()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  const qs = useMemo(() => {
    const p = new URLSearchParams();
    if (f.astronaut) p.set("astronaut", f.astronaut);
    if (f.test_type) p.set("test_type", f.test_type);
    if (f.status) p.set("status", f.status);
    if (f.from) p.set("date_from", String(new Date(f.from + "T00:00:00").getTime() / 1000));
    if (f.to) p.set("date_to", String(new Date(f.to + "T23:59:59").getTime() / 1000));
    return p.toString();
  }, [f]);
  const { data, error } = usePoll<any>(`/api/tests?${qs}`, 4000);
  const rows = data?.tests ?? [];
  const open = (id: string) => { location.hash = `/tests?id=${id}`; setSel(id); };
  return (
    <>
      <div className="page-head"><div><h1>Test History</h1>
        <p>Every test performed in ARES — reaction tests, check-ins, symptom reports and blood-test entries — saved permanently in the local database on this computer. It works without internet and survives closing and restarting ARES.</p></div>
        <div className="row"><DataTag kind="meas" /><span className="tag">{data ? `${data.counts.tests} records · ${data.counts.trials} trials` : "…"}</span></div></div>
      <Panel title="Filter">
        <div className="row" style={{ flexWrap: "wrap", gap: 10 }}>
          <label className="field">Astronaut<select value={f.astronaut} onChange={(e) => setF({ ...f, astronaut: e.target.value })}>
            <option value="">All</option>{(data?.astronauts ?? s.crew).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <label className="field">Test type<select value={f.test_type} onChange={(e) => setF({ ...f, test_type: e.target.value })}>
            <option value="">All</option>{Object.entries<string>(data?.types ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="field">Status<select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            <option value="">All</option>{(data?.statuses ?? []).map((k: string) => <option key={k} value={k}>{STATUS_TEXT[k] ?? k}</option>)}</select></label>
          <label className="field">From<input type="date" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /></label>
          <label className="field">To<input type="date" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} /></label>
          <button className="btn sm ghost" onClick={() => setF({ astronaut: "", test_type: "", status: "", from: "", to: "" })}>Clear</button>
          <a className="btn sm cyan" style={{ alignSelf: "flex-end" }} href={`/api/tests/export.csv?${qs}`} download>Export table (CSV) ↓</a>
        </div>
      </Panel>
      {error && <div className="note warn mt">Could not read the test database: {error}</div>}
      <div className="grid mt" style={{ gridTemplateColumns: sel ? "minmax(0,1fr) minmax(0,1.25fr)" : "1fr" }}>
        <Panel title={`Tests (${rows.length})`}>
          <div className="tbl-wrap" style={{ maxHeight: sel ? 900 : 620 }}><table className="tbl">
            <thead><tr><th>Date</th><th>Astronaut</th><th>Test</th><th className="r">Duration</th><th>Result</th><th>Status</th><th /></tr></thead>
            <tbody>{rows.length ? rows.map((r: any) => (
              <tr key={r.test_id} className={sel === r.test_id ? "on" : ""} style={{ cursor: "pointer" }} onClick={() => open(r.test_id)}>
                <td>{dt(r.started_at)}<div className="muted" style={{ fontSize: 11 }}>mission day {fmt(r.mission_day, 1)}</div></td>
                <td>{r.astronaut_name}</td><td>{r.test_name}</td><td className="r">{r.test_type === "pvt" ? dur(r.duration_s) : "—"}</td>
                <td>{r.summary}{r.test_type === "pvt" && r.scored === false && <div className="muted" style={{ fontSize: 11 }}>not scored</div>}</td>
                <td><Status s={STATUS_S[r.status] ?? "unknown"} text={STATUS_TEXT[r.status] ?? r.status} /></td>
                <td><button className="btn sm ghost" onClick={(e) => { e.stopPropagation(); open(r.test_id); }}>View</button></td></tr>))
              : <tr><td colSpan={7} className="muted">{data ? "No tests match these filters. Tests appear here as soon as they are performed." : "Loading…"}</td></tr>}</tbody>
          </table></div>
        </Panel>
        {sel && <TestDetail id={sel} onClose={() => { location.hash = "/tests"; setSel(null); }} />}
      </div>
    </>
  );
}

function TestDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const [t, setT] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [trend, setTrend] = useState<any>(null);
  useEffect(() => {
    setT(null); setErr(null);
    getJSON(`/api/tests/${id}`).then((d) => { setT(d); if (d.test_type === "pvt") getJSON(`/api/tests/trends?astronaut=${d.astronaut_id}`).then(setTrend).catch(() => setTrend(null)); })
      .catch((e) => setErr(String(e.message || e)));
  }, [id]);
  if (err) return <Panel title="Test details"><div className="note warn">{err}</div></Panel>;
  if (!t) return <Panel title="Test details"><div className="empty">Loading…</div></Panel>;
  const res = t.result ?? {};
  const m = res.metrics ?? {};
  const cmp = res.comparison ?? {};
  const base = res.baseline ?? {};
  const trials = t.trials ?? [];
  const isPvt = t.test_type === "pvt";
  const series = trend?.series ?? [];
  const thisIdx = series.findIndex((x: any) => x.test_id === t.test_id);
  return (
    <Panel title="Test details" right={<span className="row">
      <a className="btn sm cyan" href={`/api/tests/${t.test_id}/export.pdf`} download>PDF ↓</a>
      <a className="btn sm" href={`/api/tests/${t.test_id}/export.csv`} download>CSV ↓</a>
      <button className="btn sm ghost" onClick={onClose} aria-label="Close details">✕</button></span>}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div><h2 style={{ margin: 0 }}>{t.test_name}</h2><div className="muted">{t.astronaut_name} ({t.astronaut_id}) · test {t.test_id}</div></div>
        <Status s={STATUS_S[t.status] ?? "unknown"} text={STATUS_TEXT[t.status] ?? t.status} />
      </div>
      <div className="grid g2 mt" style={{ gap: 4 }}>
        <div className="kv1"><span>Started</span><b>{dt(t.started_at)}</b></div><div className="kv1"><span>Completed</span><b>{dt(t.completed_at)}</b></div>
        <div className="kv1"><span>Duration</span><b>{isPvt ? dur(t.duration_s) : "—"}</b></div><div className="kv1"><span>Mission day</span><b>{fmt(t.mission_day, 2)}</b></div>
        <div className="kv1"><span>Data source</span><b>{t.data_source}</b></div><div className="kv1"><span>App session</span><b>#{t.app_session ?? "—"}</b></div>
        {isPvt && <div className="kv1"><span>Configuration</span><b>{t.config?.planned_duration_s ? `${t.config.planned_duration_s} s planned` : "—"}{t.config?.max_trials ? `, max ${t.config.max_trials} trials` : ""}{t.config?.practice ? " (practice)" : ""}</b></div>}
        {isPvt && <div className="kv1"><span>Scored as PVT-B</span><b>{res.scored ? "yes" : "no"}</b></div>}
      </div>
      {isPvt ? <>
        <h4>Results</h4>
        <div className="stat-grid">{METRICS.filter(([k]) => m[k] !== undefined).map(([k, lab, u, d]) => (
          <div className="stat" key={k}><b>{m[k] == null ? "—" : fmt(m[k], d)}</b><span>{lab}{u ? ` (${u})` : ""}</span></div>))}</div>
        {m.mean_rt_ms == null && <div className="note">No valid responses were recorded, so no reaction-time values exist (shown as —, not estimated).</div>}
        <h4>Individual trials ({trials.length})</h4>
        {trials.length ? <>
          <Plot className="plot sm" data={[{ type: "bar", x: trials.map((x: any) => x.trial_no), y: trials.map((x: any) => x.rt_ms ?? 0),
            marker: { color: trials.map((x: any) => OUTCOME_COLOR[x.outcome]) }, customdata: trials.map((x: any) => OUTCOME_TEXT[x.outcome]),
            hovertemplate: "trial %{x}: %{y:.0f} ms<br>%{customdata}<extra></extra>" }]}
            layout={PLOT_LAYOUT({ hovermode: "closest", xaxis: ax("trial"), yaxis: ax("reaction time (ms)"),
              shapes: [{ type: "line", x0: 0, x1: 1, xref: "paper", y0: 355, y1: 355, line: { color: "#f2c94c", dash: "dot" } }] })} />
          <div className="legend" style={{ marginBottom: 6 }}>{Object.entries(OUTCOME_TEXT).map(([k, v]) => <span key={k}><i style={{ background: OUTCOME_COLOR[k] }} />{v} <b>{trials.filter((x: any) => x.outcome === k).length}</b></span>)}</div>
          <details><summary className="muted">Trial table</summary>
            <div className="tbl-wrap" style={{ maxHeight: 220 }}><table className="tbl"><thead><tr><th className="r">#</th><th>Outcome</th><th className="r">Reaction time</th><th className="r">Interval before</th><th className="r">Time from start</th></tr></thead>
              <tbody>{trials.map((x: any) => <tr key={x.trial_no}><td className="r">{x.trial_no}</td><td>{OUTCOME_TEXT[x.outcome]}</td><td className="r">{x.rt_ms == null ? "—" : `${fmt(x.rt_ms, 0)} ms`}</td>
                <td className="r">{x.isi_ms == null ? "—" : `${fmt(x.isi_ms / 1000, 1)} s`}</td><td className="r">{x.t_offset_ms == null ? "—" : `${fmt(x.t_offset_ms / 1000, 1)} s`}</td></tr>)}</tbody></table></div></details>
        </> : <div className="muted">No trials were recorded.</div>}
        <h4>Compared with previous test and personal baseline</h4>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Metric</th><th className="r">This test</th><th className="r">Previous test</th><th className="r">Personal baseline</th><th className="r">vs baseline</th></tr></thead>
          <tbody>{[["mean_rt_ms", "Average (ms)"], ["median_rt_ms", "Median (ms)"], ["lapses", "Lapses"], ["sd_ms", "Variability SD (ms)"], ["premature", "Premature"]].map(([k, lab]) => {
            const b = cmp.baseline?.[k], p = cmp.previous?.[k];
            return <tr key={k}><td>{lab}</td><td className="r">{m[k] == null ? "—" : fmt(m[k], k === "lapses" || k === "premature" ? 0 : 0)}</td>
              <td className="r">{p ? fmt(p.reference, 0) : "—"}</td><td className="r">{b ? fmt(b.reference, 1) : "—"}</td>
              <td className="r">{b && b.relative != null ? `${b.difference > 0 ? "+" : ""}${fmt(b.difference, 1)} (${b.relative > 0 ? "+" : ""}${fmt(b.relative * 100, 0)}%)` : "—"}</td></tr>; })}</tbody></table></div>
        <div className="muted" style={{ fontSize: 12 }}>{base.note}{cmp.previous_test ? ` Previous test: ${dt(cmp.previous_test.started_at)}.` : " No earlier completed test to compare with."}</div>
      </> : <>
        <h4>Recorded values</h4>
        {Object.entries<any>(m).map(([k, v]) => <div className="kv1" key={k}><span>{k.replace(/_/g, " ")}</span><b>{Array.isArray(v) ? (v.length ? v.join(", ").replace(/_/g, " ") : "none") : typeof v === "object" && v ? Object.entries(v).map(([a, b]) => `${a}: ${b}`).join(" · ") : String(v)}</b></div>)}
      </>}
      {res.interpretation?.length > 0 && <>
        <h4>What this means <span className="tag meas">observed differences — not a diagnosis</span></h4>
        {res.interpretation.map((x: any, i: number) => <div key={i} className="row" style={{ marginBottom: 4 }}><Status s={x.s} text={x.kind === "observed" ? "Observed" : x.kind === "status" ? "Status" : x.kind === "data" ? "Data" : "Note"} /><span className="ink2">{x.text}</span></div>)}
      </>}
      {res.assessment && <div className="kv1 mt"><span>{res.assessment.category ?? "Model-generated assessment"} <DataTag kind="model" /></span><b>Behavioral readiness: {res.assessment.label}</b></div>}
      {isPvt && trend && <>
        <h4>Performance over the mission ({trend.n_tests} completed tests)</h4>
        {series.length >= 2 ? <>
          <Plot className="plot sm" data={[
            { x: series.map((_: any, i: number) => i + 1), y: series.map((x: any) => x.mean_rt_ms), mode: "lines+markers", name: "average", line: { color: "#3fd8ff", width: 2 },
              marker: { size: series.map((_: any, i: number) => (i === thisIdx ? 13 : 7)), color: series.map((_: any, i: number) => (i === thisIdx ? "#ffffff" : "#3fd8ff")) },
              customdata: series.map((x: any) => dt(x.started_at)), hovertemplate: "test %{x} (%{customdata}): %{y:.0f} ms<extra></extra>" },
            { x: series.map((_: any, i: number) => i + 1), y: series.map((x: any) => x.sd_ms), mode: "lines", name: "variability (SD)", line: { color: "#8fa8ff", dash: "dot", width: 1.5 }, yaxis: "y", hovertemplate: "SD %{y:.0f} ms<extra></extra>" },
          ]} layout={PLOT_LAYOUT({ hovermode: "closest", showlegend: true, legend: { orientation: "h", y: 1.15, font: { size: 10 } }, xaxis: ax("saved completed test #"), yaxis: ax("ms"),
            shapes: trend.baseline?.values?.mean_rt_ms ? [{ type: "line", x0: 0, x1: 1, xref: "paper", y0: trend.baseline.values.mean_rt_ms, y1: trend.baseline.values.mean_rt_ms, line: { color: "#2fd39b", dash: "dash" } }] : [] })} />
          <Plot className="plot xs" data={[{ type: "bar", x: series.map((_: any, i: number) => i + 1), y: series.map((x: any) => x.lapses), marker: { color: "#f2c94c" }, hovertemplate: "test %{x}: %{y} lapses<extra></extra>" }]}
            layout={PLOT_LAYOUT({ hovermode: "closest", xaxis: ax("saved completed test #"), yaxis: ax("lapses") })} />
          <div className="muted" style={{ fontSize: 11 }}>Dashed green line = personal baseline; large white point = this test.</div>
        </> : <div className="muted">At least two completed tests are needed for a chart.</div>}
        <div className="mt"><b>Observed trends</b> <span className="tag meas">from saved results</span></div>
        {trend.observed.length ? trend.observed.map((o: any) => <div key={o.metric} className="row" style={{ marginBottom: 3 }}><Status s={o.notable ? "watch" : "stable"} text={o.notable ? "Notable" : "Small"} /><span className="ink2">{o.text}</span></div>)
          : <div className="muted">{trend.note}</div>}
        {trend.model && <div className="mt"><b>Model-generated assessment</b> <DataTag kind="model" /><div className="ink2">{trend.model.label} — {trend.model.text}</div></div>}
        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>{trend.note}</div>
      </>}
    </Panel>
  );
}
