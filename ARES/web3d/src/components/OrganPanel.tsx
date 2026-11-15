import { useEffect, useState } from "react";
import { fmt, relT, STATE_COLOR, STATE_LABEL, usePoll } from "../api";
import { DataTag, Plot, PLOT_LAYOUT, Status } from "../ui";
import { STATUS_S, STATUS_TEXT } from "../pages/Alertness";

/* Organ dossier for the 3D hologram. Everything shown comes from GET /api/organs/{region}: the actual backend health
   events, measurements vs the astronaut's own baseline, onboard protocols and knowledge base, and stored history.
   Categories are always labelled (sensor / derived / test / lab / AI prediction / research / population estimate). */
const SEV_TEXT: Record<string, string> = { normal: "Normal", observation: "Observation", elevated: "Elevated concern", critical: "Critical alert", unknown: "Insufficient data", not_monitored: "Insufficient data" };
const EV: Record<string, string> = { "established-spaceflight": "Established (NASA-recognised risk)", "spaceflight-research": "Spaceflight research data", theoretical: "Possible risk (not established)" };
const CAT_CLASS: Record<string, string> = { "direct sensor measurement": "meas", "derived indicator": "meas derived", "test result": "meas", "laboratory marker": "meas", "AI prediction": "model", "research evidence (mouse spaceflight studies)": "real", "population estimate": "model", "detection rule": "model" };
const TREND: Record<string, string> = { worsening: "Getting worse", improving: "Improving", stable: "Steady", unknown: "Not enough history", "getting worse": "Getting worse", steady: "Steady" };
const Cat = ({ c }: { c?: string }) => (c ? <span className={`tag ${CAT_CLASS[c] ?? ""}`}>{c}</span> : null);
const ax = (t: string) => ({ gridcolor: "rgba(110,170,255,.08)", title: { text: t, font: { size: 10 } } });

function Sec({ k, title, children, open = true }: { k: string; title: string; children: any; open?: boolean }) {
  return <details className={`osec ${k}`} open={open}><summary><em>{k}</em>{title}</summary><div className="osec-body">{children}</div></details>;
}

function MeasTable({ ms }: { ms: any[] }) {
  if (!ms.length) return <div className="muted">No measurement is linked to this item.</div>;
  return (
    <div className="mcards">{ms.map((m: any) => (
      <div key={m.key} className={`mcard ${m.sev >= 2 ? "bad" : m.sev === 1 ? "warn" : ""}`}>
        <div className="mc-top"><span className="mc-label">{m.label}</span><Cat c={m.category} /></div>
        <div className="mc-vals">
          <div><span>Current</span><b className="num">{m.current ?? "—"} <small>{m.unit}</small></b></div>
          <div><span>Usual (baseline)</span><b className="num">{m.baseline ?? "—"}</b></div>
          <div><span>Difference</span><b className="num">{m.difference == null ? "—" : `${m.difference > 0 ? "+" : ""}${m.difference}`}</b></div>
          <div><span>Personal range</span><b className="num">{m.band ? `${m.band[0]}–${m.band[1]}` : "—"}</b></div>
          <div><span>Trend</span><b>{TREND[m.trend] ?? m.trend}</b></div>
        </div>
        {m.reliable === false && <div className="muted" style={{ fontSize: 11 }}>No recent reliable reading — not used for the organ colour.</div>}
      </div>))}</div>
  );
}

function Actions({ g }: { g: any }) {
  const im = g.immediate_action;
  return <>
    <div className="decision">
      <div><span>Check immediately / extra measurements</span>{im.measurements.length ? im.measurements.join("; ") : "None listed in the procedures"}</div>
      <div><span>Notify the crew medical officer?</span>{im.notify_cmo}</div>
      <div><span>Stop the current activity?</span>{im.stop_activity}</div>
      <div><span>Earth medical team</span>{im.send_to_earth}</div>
    </div>
    {im.protocols.map((p: any) => (
      <div className="proto" key={p.id}>
        <b>[{p.id}] {p.title}</b><span className="unapproved">{p.approval}</span>
        <ol>{p.steps.map((s: string, i: number) => <li key={i}>{s}</li>)}</ol>
        <div className="kv1"><span>Escalate (further medical assessment) if</span><b>{Array.isArray(p.escalate_if) ? p.escalate_if.join("; ") : p.escalate_if}</b></div>
        <div className="src">Source: {p.source.title}</div>
      </div>))}
    {!im.protocols.length && <div className="muted">No onboard procedure is stored for this item.</div>}
    <div className="muted" style={{ fontSize: 11 }}>Procedures are shown verbatim from the onboard protocol database ({im.kb_status}).</div>
  </>;
}

function LongTerm({ g }: { g: any }) {
  return <ul className="lt">{g.long_term_effects.map((e: any, i: number) => (
    <li key={i}><span className={`ev-tag ev-${e.evidence}`}>{EV[e.evidence] ?? e.evidence}</span>{e.text}
      <div className="muted" style={{ fontSize: 11 }}>{e.source.url ? <a href={e.source.url} target="_blank" rel="noreferrer">{e.source.title}</a> : e.source.title}</div></li>))}</ul>;
}

function Care({ g }: { g: any }) {
  const c = g.long_term_care;
  return <>
    <div className="kv1"><span>Recommended monitoring</span><b>{c.monitoring.join("; ")}</b></div>
    <div className="kv1"><span>Follow-up measurements</span><b>{c.follow_up.join("; ")}</b></div>
    <div className="kv1"><span>Preventive measures</span><b>{c.prevention.join("; ")}</b></div>
    <div className="kv1"><span>Health trends to watch</span><b>{c.watch.join(", ")}</b></div>
    {c.escalate_if?.length > 0 && <div className="kv1"><span>Conditions requiring escalation</span><b>{c.escalate_if.join("; ")}</b></div>}
  </>;
}

function VitalHistory({ d }: { d: any }) {
  const h = d.history;
  if (!h?.series || !h.t?.length) return <div className="muted">No history recorded yet in this session.</div>;
  const x = h.t.map((t: number) => (t - h.t0) / 60);
  return <>{Object.entries<any>(h.series).map(([k, sr]) => (
    <div key={k}>
      <div className="row" style={{ justifyContent: "space-between" }}><b style={{ fontSize: 12 }}>{sr.label} ({sr.unit})</b><Cat c={sr.category} /></div>
      <Plot className="plot xs" data={[
        { x, y: sr.hi, mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
        { x, y: sr.lo, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(63,216,255,.10)", hoverinfo: "skip" },
        { x, y: sr.expected, mode: "lines", line: { color: "rgba(167,185,212,.6)", dash: "dot", width: 1 }, name: "usual", hovertemplate: "usual %{y:.1f}<extra></extra>" },
        { x, y: sr.value, mode: "lines", line: { color: "#3fd8ff", width: 1.8 }, name: sr.label, hovertemplate: "%{y:.1f} " + sr.unit + " at %{x:.1f} h<extra></extra>" },
      ]} layout={PLOT_LAYOUT({ margin: { l: 40, r: 8, t: 4, b: 26 }, xaxis: ax("hours since monitoring start"), yaxis: ax("") })} />
    </div>))}
    <div className="muted" style={{ fontSize: 11 }}>{h.note}</div></>;
}

function BrainHistory({ d }: { d: any }) {
  const h = d.history ?? {};
  const tr = h.pvt_trend;
  const ser = tr?.series ?? [];
  const b = h.behavioral_series ?? {};
  return <>
    <b style={{ fontSize: 12 }}>Reaction tests saved for this astronaut</b> <span className="tag meas">test result</span>
    {ser.length ? <Plot className="plot xs" data={[{ x: ser.map((_: any, i: number) => i + 1), y: ser.map((s: any) => s.mean_rt_ms), mode: "lines+markers", line: { color: "#3fd8ff", width: 2 },
      customdata: ser.map((s: any) => new Date(s.started_at * 1000).toLocaleString()), hovertemplate: "test %{x} (%{customdata}): %{y:.0f} ms<extra></extra>" }]}
      layout={PLOT_LAYOUT({ hovermode: "closest", xaxis: ax("saved completed test #"), yaxis: ax("average reaction time (ms)"),
        shapes: tr?.baseline?.values?.mean_rt_ms ? [{ type: "line", x0: 0, x1: 1, xref: "paper", y0: tr.baseline.values.mean_rt_ms, y1: tr.baseline.values.mean_rt_ms, line: { color: "#2fd39b", dash: "dash" } }] : [] })} />
      : <div className="muted">No completed reaction tests saved yet — run one on the Reaction Time Test page.</div>}
    {tr?.observed?.map((o: any) => <div key={o.metric} className="ink2" style={{ fontSize: 12 }}>• {o.text} <span className="tag meas">observed</span></div>)}
    {(h.saved_tests ?? []).length > 0 && <div className="tbl-wrap mt" style={{ maxHeight: 180 }}><table className="tbl"><thead><tr><th>Date</th><th>Test</th><th>Result</th><th>Status</th><th /></tr></thead>
      <tbody>{h.saved_tests.slice(0, 12).map((t: any) => <tr key={t.test_id}><td>{new Date(t.started_at * 1000).toLocaleString()}</td><td>{t.test_name}</td><td>{t.summary}</td>
        <td><Status s={STATUS_S[t.status] ?? "unknown"} text={STATUS_TEXT[t.status] ?? t.status} /></td><td><a className="btn sm ghost" href={`#/tests?id=${t.test_id}`}>Open</a></td></tr>)}</tbody></table></div>}
    {b.pvt_day?.length > 0 && <>
      <div className="mt"><b style={{ fontSize: 12 }}>Daily alertness battery over the mission</b> <DataTag kind="sim" /></div>
      <Plot className="plot xs" data={[{ x: b.pvt_day, y: b.speed, mode: "lines+markers", line: { color: "#8fa8ff", width: 1.5 }, marker: { size: 5 }, hovertemplate: "day %{x:.1f}: speed %{y:.2f}/s<extra></extra>" },
        ...(b.ci_day?.length ? [{ x: b.ci_day, y: b.samn_perelli, yaxis: "y2", mode: "markers", marker: { color: "#f2c94c", size: 6, symbol: "diamond" }, hovertemplate: "day %{x:.1f}: fatigue %{y}/7<extra></extra>" }] : [])]}
        layout={PLOT_LAYOUT({ hovermode: "closest", xaxis: ax("mission day"), yaxis: ax("response speed (1/s)"), yaxis2: { overlaying: "y", side: "right", range: [1, 7], title: { text: "fatigue 1–7", font: { size: 10 } }, gridcolor: "rgba(0,0,0,0)" } })} />
      <div className="muted" style={{ fontSize: 11 }}>{h.behavioral_series_note}</div></>}
  </>;
}

function LabHistory({ d }: { d: any }) {
  const labs = d.history?.labs ?? {};
  const any = Object.values<any>(labs).some((v) => v.length);
  if (!any) return <div className="muted">No blood-test results recorded for this organ yet.</div>;
  return <>{Object.entries<any>(labs).filter(([, v]) => v.length).map(([k, v]) => (
    <div key={k}><b style={{ fontSize: 12 }}>{d.measurements[k]?.label ?? k}</b> <span className="tag meas">laboratory marker</span>
      <Plot className="plot xs" data={[{ x: v.map((r: any) => (r.t - d.t0) / 60), y: v.map((r: any) => r.value), mode: "lines+markers", line: { color: "#3fd8ff" }, hovertemplate: "%{y}<extra></extra>" }]}
        layout={PLOT_LAYOUT({ hovermode: "closest", xaxis: ax("hours since monitoring start"), yaxis: ax(d.measurements[k]?.unit ?? ""),
          shapes: d.history.preflight?.[k] != null ? [{ type: "line", x0: 0, x1: 1, xref: "paper", y0: d.history.preflight[k], y1: d.history.preflight[k], line: { color: "#2fd39b", dash: "dash" } }] : [] })} />
    </div>))}<div className="muted" style={{ fontSize: 11 }}>Dashed line = this astronaut's pre-flight value (simulated).</div></>;
}

export default function OrganPanel({ region, aid, onClose, onFocus }: { region: string; aid: string; onClose: () => void; onFocus: () => void }) {
  const { data: d, error } = usePoll<any>(`/api/organs/${region}?astronaut=${aid}`, 3000);
  const [evIdx, setEvIdx] = useState(0);
  useEffect(() => setEvIdx(0), [region, aid]);
  if (error && !d) return <div className="note warn">Could not load organ information: {error}</div>;
  if (!d) return <div className="empty">Loading organ information…</div>;
  const events: any[] = d.events ?? [];
  const ev = events[Math.min(evIdx, Math.max(events.length - 1, 0))];
  const g = ev ? d.guidance?.[ev.concern] : null;
  const ref = !events.some((e) => e.status === "active") ? d.reference_guidance : null;
  const sevColor = STATE_COLOR[d.state] ?? STATE_COLOR.unknown;
  return (
    <div className="organ" style={{ ["--sev" as any]: sevColor }}>
      <div className="organ-head">
        <div>
          <h2>{d.label}</h2>
          <div className="muted">{d.system} · {d.astronaut_name}{d.regions && Object.keys(d.regions).length > 1 ? ` · ${Object.keys(d.regions).length} structures` : ""}</div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm ghost" onClick={onFocus} title="Fly the camera to this organ">Focus</button>
          <button className="btn sm ghost" onClick={onClose} title="Close and return to the full-body view" aria-label="Close">✕</button>
        </div>
      </div>
      <div className="organ-status">
        <span className="sev-pill" style={{ background: sevColor }}>{SEV_TEXT[d.state] ?? d.state}</span>
        <span className={`alert-pill ${d.active_alert ? "on" : ""}`}>{d.active_alert ? `Active alert · ${d.active_events} event${d.active_events > 1 ? "s" : ""}` : "No active alert"}</span>
        <span className="muted" style={{ fontSize: 11 }}>{STATE_LABEL[d.state]}</span>
      </div>
      {!d.data_available && <div className="nodata">{d.message}</div>}
      <p className="organ-what">{d.what_is_happening}</p>

      {events.length > 0 && <div className="ev-tabs" role="tablist">{events.map((e, i) => (
        <button key={e.event_id} role="tab" aria-selected={i === evIdx} className={`ev-tab ${i === evIdx ? "on" : ""}`} onClick={() => setEvIdx(i)}
          style={{ ["--c" as any]: STATE_COLOR[e.state] ?? STATE_COLOR.unknown }}>
          <i />{e.title}<small>{e.status === "active" ? SEV_TEXT[e.state] : e.status}</small></button>))}</div>}

      {ev && <>
        <Sec k="A" title="What is happening?">
          <div className="row" style={{ flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
            <span className="tag">{ev.event_id}</span><span className="tag">{ev.system}</span><span className="tag sim">{ev.data_source}</span>
            {ev.incident && <a className="tag" href="#/emergency" title="Open in Emergency Command">Health event #{ev.incident.incident_id} · L{ev.incident.level} · {ev.incident.workflow_status}</a>}
          </div>
          <MeasTable ms={Object.values(ev.measurements ?? {})} />
          <div className="grid g2" style={{ gap: 4, marginTop: 6 }}>
            <div className="kv1"><span>Detected</span><b>{ev.detected_at == null ? "—" : `${relT(ev.detected_at, d.t0)} (${fmt((d.t - ev.detected_at), 0)} min ago)`}</b></div>
            <div className="kv1"><span>Improving or worsening?</span><b>{TREND[ev.trend] ?? ev.trend}</b></div>
          </div>
          {ev.pattern_note && <div className="note">{ev.pattern_note}</div>}
        </Sec>
        <Sec k="B" title="Why was this alert generated?">
          <ul className="evlist">{ev.evidence.map((x: any, i: number) => <li key={i}><Cat c={x.category} /> {x.text}{x.quality != null && <span className="muted"> · sensor quality {Math.round(x.quality * 100)}%</span>}</li>)}</ul>
          {ev.confidence ? <>
            <div className="kv1"><span>Model detection confidence <DataTag kind="model" /></span><b>{ev.confidence.confidence_label ?? "—"}{ev.confidence.detection_confidence != null ? ` (${fmt(ev.confidence.detection_confidence, 2)})` : ""}</b></div>
            <div className="kv1"><span>Sensor reliability</span><b>{Object.values<any>(ev.confidence.sensor_reliability).map((r: any, i: number) => <span key={i} style={{ marginRight: 8 }}>{r.sensor}: {Math.round(r.quality * 100)}%{r.reliable ? "" : " (unreliable)"}</span>)}</b></div>
            {ev.confidence.uncertainty.length > 0 && <div className="kv1"><span>Uncertainty</span><b>{ev.confidence.uncertainty.join(" · ")}</b></div>}
            <div className="muted" style={{ fontSize: 11 }}>{ev.confidence.note}</div>
          </> : <div className="muted" style={{ fontSize: 12 }}>No model confidence applies to this item.</div>}
          {d.ai_predictions && <div className="ai-box"><b>AI predictions</b> <DataTag kind="model" />
            <div className="row" style={{ gap: 14, flexWrap: "wrap" }}><span>30-min deterioration risk <b className="num">{d.ai_predictions.risk_30min == null ? "—" : `${Math.round(d.ai_predictions.risk_30min * 100)}%`}</b></span>
              <span>Unusual-pattern score <b className="num">{fmt(d.ai_predictions.anomaly_score, 2)}</b></span>
              <span>If the trend continues (30 min) <b>{d.ai_predictions.projected_state_30min ? SEV_TEXT[d.ai_predictions.projected_state_30min] : "—"}</b></span></div>
            <div className="muted" style={{ fontSize: 11 }}>{d.ai_predictions.note}</div></div>}
        </Sec>
        <Sec k="C" title="Immediate action">{g ? <Actions g={g} /> : <div className="muted">No guidance is stored for this item.</div>}</Sec>
        <Sec k="D" title="Possible long-term effects" open={false}>{g ? <LongTerm g={g} /> : <div className="muted">No knowledge-base entry.</div>}</Sec>
        <Sec k="E" title="Long-term management" open={false}>{g ? <Care g={g} /> : <div className="muted">No knowledge-base entry.</div>}</Sec>
      </>}

      {!ev && <>
        <Sec k="A" title="What is happening?">
          {Object.keys(d.measurements ?? {}).length ? <MeasTable ms={Object.values(d.measurements)} /> : <div className="muted">No measurement available.</div>}
          {Object.values<any>(d.measurements ?? {}).filter((m) => m.note).map((m, i) => <div className="note" key={i}>{m.note}</div>)}
        </Sec>
        <Sec k="C" title="Immediate action"><div className="muted">No active concern for this organ — no immediate action is required.</div></Sec>
        {ref && <>
          <Sec k="D" title="Possible long-term effects (general information)" open={false}><div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Reference information for {ref.system.toLowerCase()} — there is no active concern.</div><LongTerm g={ref} /></Sec>
          <Sec k="E" title="Long-term management (general information)" open={false}><Care g={ref} /></Sec>
        </>}
      </>}

      {d.model_assessment && <div className="ai-box"><b>Behavioral readiness: {d.model_assessment.label}</b> <DataTag kind="model" />
        <div className="muted" style={{ fontSize: 11 }}>{d.model_assessment.note} This is a functional indicator, not a structural brain finding.</div></div>}

      {d.population_estimate && <Sec k="P" title="Estimated change where nothing is measured">
        <div className="row" style={{ gap: 6 }}><span className="tag model">population estimate</span><span className="muted">mission day {d.population_estimate.mission_day}</span></div>
        <p className="ink2" style={{ fontSize: 12 }}>{d.population_estimate.basis}</p>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Bone</th><th>Estimated density change so far</th></tr></thead>
          <tbody>{Object.entries<any>(d.population_estimate.per_region).map(([r, v]) => <tr key={r}><td>{d.regions?.[r]?.label ?? r}</td>
            <td>{v.applies ? `${v.estimated_change_pct[0]}% to ${v.estimated_change_pct[1]}% (population average)` : <span className="muted">{v.reason}</span>}</td></tr>)}</tbody></table></div>
        <div className="note warn">{d.population_estimate.caveat}</div>
        <div className="muted" style={{ fontSize: 11 }}>{d.population_estimate.sources.map((s: any) => s.title).join(" · ")}</div>
      </Sec>}

      {Object.keys(d.research_evidence ?? {}).length > 0 && <Sec k="R" title="Spaceflight research evidence (mice — not this astronaut)" open={!d.data_available}>
        {Object.entries<any>(d.research_evidence).map(([r, items]) => <div key={r}><b style={{ fontSize: 12 }}>{d.regions?.[r]?.label ?? r}</b>
          <ul className="evlist">{items.map((x: any, i: number) => <li key={i}><span className="tag real">research evidence</span> <b>{x.title}</b> — {x.summary} <span className="muted">[{x.dataset}]</span></li>)}</ul></div>)}
      </Sec>}

      <Sec k="F" title="Historical data" open={!!ev}>
        {d.history?.series ? <VitalHistory d={d} /> : d.history?.labs ? <LabHistory d={d} /> : d.group === "brain" ? <BrainHistory d={d} />
          : <div className="muted">No historical measurements exist for this organ.</div>}
        {d.previous_alerts?.length > 0 && <>
          <h5>Previous alerts for this organ system</h5>
          <div className="tbl-wrap" style={{ maxHeight: 160 }}><table className="tbl"><thead><tr><th>When</th><th>Event</th><th className="r">Peak</th><th>Status</th></tr></thead>
            <tbody>{d.previous_alerts.map((a: any, i: number) => <tr key={i}><td>{a.source === "this session" ? relT(a.opened, d.t0) : a.source}</td><td>#{a.incident_id} {(a.title ?? "").replace("EVENT: ", "").toLowerCase()}</td>
              <td className="r">L{a.peak_level ?? "—"}</td><td>{a.status}</td></tr>)}</tbody></table></div></>}
        {d.timeline?.length > 0 && <>
          <h5>Timeline of relevant events</h5>
          <ul className="timeline">{d.timeline.slice(0, 12).map((t: any, i: number) => <li key={i} className={`l${t.level}`}><span className="num">{relT(t.t, d.t0)}</span> {t.text}</li>)}</ul></>}
      </Sec>
      <div className="cat-legend">{d.categories_legend?.map((c: string) => <Cat key={c} c={c} />)}</div>
    </div>
  );
}
