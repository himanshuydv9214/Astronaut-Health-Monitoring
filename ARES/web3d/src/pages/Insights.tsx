import { useApp } from "../App";
import { usePoll } from "../api";
import { DataTag, LevelPill, Panel, Plot, PLOT_LAYOUT } from "../ui";

const li = (a: string[]) => (a?.length ? <ul style={{ margin: "2px 0", paddingLeft: 18, color: "var(--ink-2)" }}>{a.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted" style={{ margin: 2 }}>None.</p>);

export default function Insights() {
  const { s } = useApp();
  const { data: sys } = usePoll<any>("/api/system", 5000);
  const det = s.detail, r = det.recent, x0 = s.t - s.demo_minute;
  const x = r.t.map((t: number) => (t - x0) / 60);
  const ex = det.explanation, cls = det.classification;
  const sh = (ex.influencing_parameters || []).slice().reverse();
  const cr = Object.entries<any>(det.correlations || {});
  const mm = sys?.model_monitoring;
  return (
    <>
      <div className="page-head"><div><h1>Unusual Health Changes</h1>
        <p>What the onboard AI sees for {det.profile.name}: an unusual-pattern score, a 30-minute risk estimate, and a plain explanation of why. All models run locally — no internet needed.</p></div>
        <LevelPill level={cls.level} text={`Health risk level: ${cls.label}`} /></div>
      <div className="grid g2">
        <Panel title="Unusual-pattern score and 30-minute risk" info="ai" right={<DataTag kind="model" />}>
          <Plot data={[
            { x, y: r.anomaly, mode: "lines", name: "Unusual-pattern score", line: { color: "#3fd8ff", width: 2 }, hovertemplate: "unusual %{y:.2f}<extra></extra>" },
            { x, y: r.risk, mode: "lines", name: "30-min risk", line: { color: "#ff8a3d", width: 2 }, hovertemplate: "risk %{y:.2f}<extra></extra>" },
            { x: [x[0], x[x.length - 1]], y: [0.5, 0.5], mode: "lines", name: "worth a look", line: { color: "#5f7da6", width: 1, dash: "dot" }, hoverinfo: "skip" },
          ]} layout={PLOT_LAYOUT({ showlegend: true, legend: { orientation: "h", y: 1.14, x: 0 }, margin: { l: 36, r: 8, t: 24, b: 26 },
            yaxis: { gridcolor: "rgba(110,170,255,.08)", range: [0, 1.02] }, xaxis: { gridcolor: "rgba(110,170,255,.08)", ticksuffix: " h" } })} />
        </Panel>
        <Panel title="Why: plain explanation of the current state">
          <div className="row" style={{ marginBottom: 6 }}><LevelPill level={cls.level} /><span className="muted">confidence {cls.confidence_label} ({cls.confidence})</span></div>
          <h4>Reasons</h4>{li(cls.reasons)}
          <h4>Compared with this astronaut's own normal</h4>{li(ex.baseline_text)}
          <h4>Changes that are building up</h4>{li(ex.significant_changes)}
          <h4>Missing or unreliable information</h4>{li(ex.missing)}
          <p className="muted" style={{ fontSize: 12 }}>{ex.note}</p>
        </Panel>
      </div>
      <div className="grid g3 mt">
        <Panel title="What drives the risk estimate" info="shap" right={<DataTag kind="model" />}>
          <Plot className="plot sm" data={sh.length ? [{ type: "bar", orientation: "h", x: sh.map((q: any) => q.contribution), y: sh.map((q: any) => `${q.feature} = ${q.value}`),
            marker: { color: sh.map((q: any) => (q.contribution > 0 ? "#ff8a3d" : "#3fd8ff")) }, hovertemplate: "%{y}<br>%{x:+.3f}<extra></extra>" }] : []}
            layout={PLOT_LAYOUT({ margin: { l: 150, r: 8, t: 4, b: 26 }, hovermode: "closest", xaxis: { gridcolor: "rgba(110,170,255,.08)", zeroline: true, zerolinecolor: "#3a5578", title: { text: "← lowers risk · raises risk →", font: { size: 10 } } },
              annotations: sh.length ? [] : [{ text: "No risk estimate yet", showarrow: false, font: { color: "#6c819f" } }] })} />
        </Panel>
        <Panel title="How readings move together (last hour)">
          <Plot className="plot sm" data={cr.length ? [{ type: "bar", x: cr.map((c) => c[0].replace("~", " ~ ")), y: cr.map((c) => c[1]), marker: { color: cr.map((c) => (c[1] >= 0 ? "#3b82ff" : "#3fd8ff")) }, hovertemplate: "%{x}: r = %{y:.2f}<extra></extra>" }] : []}
            layout={PLOT_LAYOUT({ hovermode: "closest", yaxis: { gridcolor: "rgba(110,170,255,.08)", range: [-1, 1], zeroline: true, zerolinecolor: "#3a5578" }, margin: { l: 32, r: 6, t: 4, b: 54 } })} />
          {det.patterns.length ? det.patterns.map((p: any) => <div key={p.id} className="note warn">Pattern: {p.name}</div>)
            : <p className="muted" style={{ fontSize: 12, margin: 0 }}>No known combined pattern. Patterns are hypotheses for the medical officer, never diagnoses.</p>}
        </Panel>
        <Panel title="AI and system health" info="modelhealth">
          {sys ? <>
            {Object.entries<any>(sys.models.files).map(([n, f]) => <div key={n} className="kv1"><span>{n}</span><b>{f.hash_ok ? "checksum OK" : "MISMATCH"}</b></div>)}
            <div className="kv1"><span>Unusual-pattern flag rate (24 h)</span><b className="num">{mm.anomaly_flag_rate_24h == null ? "—" : `${(100 * mm.anomaly_flag_rate_24h).toFixed(2)}% (expected 0.5%)`}</b></div>
            <div className="kv1"><span>Inputs outside training range</span><b className="num">{mm.feature_out_of_range_frac_24h == null ? "—" : `${(100 * mm.feature_out_of_range_frac_24h).toFixed(2)}%`}</b></div>
            {typeof sys.integrity.store === "object" && Object.entries<any>(sys.integrity.store).map(([t, v]) => <div key={t} className="kv1"><span>Local record: {t}</span><b>{v.rows} rows · {v.intact ? "intact" : "TAMPERED"}</b></div>)}
            <div className="kv1"><span>Processing time per minute</span><b className="num">{sys.tick_ms} ms</b></div>
          </> : <div className="loading">Loading…</div>}
        </Panel>
      </div>
    </>
  );
}
