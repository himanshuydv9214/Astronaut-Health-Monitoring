import { ago } from "../api";

const EV: Record<string, string> = {
  "established-spaceflight": "NASA-recognised risk", "spaceflight-research": "NASA research data", theoretical: "Possible (not established)",
};

export default function Guidance({ g, compact = false }: { g: any; compact?: boolean }) {
  if (!g) return <div className="empty">Loading guidance…</div>;
  if (!g.concern) return <div className="note">{g.note}</div>;
  const h = g.what_is_happening, im = g.immediate_action, care = g.long_term_care;
  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <b style={{ fontSize: 15 }}>{g.title}</b><span className="muted">· {g.system}</span>
        <span className="unapproved">{g.kb_status.split(" - ")[0]} knowledge base v{g.kb_version}</span>
      </div>
      <div className={compact ? "stack" : "guide"}>
        <div className="gsec a">
          <h5><em>A</em>What is happening?</h5>
          <p style={{ margin: "2px 0 6px" }}>{h.summary}</p>
          {h.changed.length > 0 && (
            <ul>{h.changed.map((c: any) => (
              <li key={c.key}><b>{c.label}</b>: {c.value} {c.unit} (usual {c.usual}) — {c.direction}
                {c.for_min ? `, for ${c.for_min} min` : ""}, <i>{c.trend}</i></li>))}</ul>)}
          <div className="kv1"><span>First detected</span><b>{h.first_detected_min == null ? "—" : ago(h.minutes_since)}</b></div>
          <div className="kv1"><span>Getting better or worse?</span><b>{h.trend}</b></div>
        </div>
        <div className="gsec b">
          <h5><em>B</em>Immediate action</h5>
          <div className="decision">
            <div><span>Stop current activity?</span>{im.stop_activity}</div>
            <div><span>Tell the medical officer?</span>{im.notify_cmo}</div>
            <div><span>Send to Earth?</span>{im.send_to_earth}</div>
            <div><span>Extra measurements</span>{im.measurements.length ? im.measurements.slice(0, 3).join("; ") : "None listed"}</div>
          </div>
          {im.protocols.map((p: any) => (
            <div className="proto" key={p.id}>
              <b>[{p.id}] {p.title}</b><span className="unapproved">{p.approval}</span>
              <ol>{p.steps.slice(0, compact ? 4 : 8).map((s: string, i: number) => <li key={i}>{s}</li>)}</ol>
              <div className="src">Source: {p.source.title}</div>
            </div>))}
          {!im.protocols.length && <p className="muted">No onboard procedure applies (no measurement for this structure).</p>}
        </div>
        <div className="gsec c">
          <h5><em>C</em>Possible long-term effects</h5>
          <ul>{g.long_term_effects.map((e: any, i: number) => (
            <li key={i}><span className={`ev-tag ev-${e.evidence}`}>{EV[e.evidence]}</span>{e.text}
              <div className="muted" style={{ fontSize: 11 }}>{e.source.url ? <a href={e.source.url} target="_blank" rel="noreferrer">{e.source.title}</a> : e.source.title}</div></li>))}</ul>
        </div>
        <div className="gsec d">
          <h5><em>D</em>Long-term care and prevention</h5>
          <div className="kv1"><span>How often to check</span><b>{care.monitoring.join("; ")}</b></div>
          <div className="kv1"><span>Follow-up</span><b>{care.follow_up.join("; ")}</b></div>
          <div className="kv1"><span>Prevention</span><b>{care.prevention.join("; ")}</b></div>
          <div className="kv1"><span>Trends to watch</span><b>{care.watch.join(", ")}</b></div>
          {care.escalate_if.length > 0 && <div className="kv1"><span>Escalate if</span><b>{care.escalate_if.slice(0, 3).join("; ")}</b></div>}
        </div>
      </div>
    </div>
  );
}
