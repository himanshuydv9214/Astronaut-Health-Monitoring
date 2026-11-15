import { useEffect, useState } from "react";
import { useApp } from "../App";
import { fmt, postJSON, relT, usePoll } from "../api";
import Guidance from "../components/Guidance";
import { LevelPill, Panel, Plot, PLOT_LAYOUT, Status, useToast } from "../ui";

const SYS: Record<string, string> = {
  "OXYGEN SATURATION": "Lungs and breathing", RESPIRATORY: "Lungs and breathing", "CARDIAC RHYTHM": "Heart",
  "CARDIOVASCULAR / FLUID": "Heart and circulation", THERMAL: "Whole body (temperature)", "MULTI-PARAMETER": "Several body systems",
  "SLEEP / FATIGUE": "Alertness and sleep", RADIATION: "Radiation environment", SENSOR: "Monitoring equipment", CO2: "Cabin air",
};
const systemOf = (ev?: string) => { const e = (ev || "").toUpperCase(); return Object.entries(SYS).find(([k]) => e.includes(k))?.[1] ?? "—"; };
const STATUS_S: Record<string, string> = { active: "critical", "resolved - awaiting review": "watch", closed: "good" };

function Detail({ id, t0 }: { id: number; t0: number }) {
  const { data, reload } = usePoll<any>(`/api/emergencies/${id}`, 1500);
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  if (!data) return <div className="loading">Loading incident #{id}…</div>;
  const w = data.workflow, rep = data.report || {}, g = data.guidance;
  const closed = w.status === "closed";
  const act = async (action: string, label: string, note?: string) => {
    setBusy(action);
    try { await postJSON(`/api/emergencies/${id}/action`, { action, note }); toast(`#${id}: ${label}`); reload(); }
    catch (e) { toast(`${label} not possible: ${(e as Error).message}`, "err"); }
    setBusy(null);
  };
  const download = async () => {
    try {
      const r = await fetch(`/api/emergencies/${id}/report.md`); const txt = await r.text();
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([txt], { type: "text/markdown" }));
      a.download = `ARES_incident_${id}.md`; a.click(); URL.revokeObjectURL(a.href); toast(`Report for #${id} downloaded (also logged)`); reload();
    } catch (e) { toast(`Report failed: ${(e as Error).message}`, "err"); }
  };
  const step = (k: string) => w.steps.find((s: any) => s.key === k);
  const h = data.history;
  const keys = (rep.abnormal_measurements || []).map((m: any) => m.key || null).filter(Boolean) as string[];
  const trig = (rep.abnormal_measurements || []) as any[];
  const keyOf = (label: string) => ({ "Heart rate": "hr", SpO2: "spo2", "Respiratory rate": "rr", "Systolic BP": "sbp", "Diastolic BP": "dbp", "Core temp (est.)": "temp", "HRV (RMSSD)": "hrv_rmssd" } as any)[label];
  const plotKeys = Array.from(new Set([...keys, ...trig.map((m) => keyOf(m.parameter)).filter(Boolean)])).slice(0, 3) as string[];
  const rate = (k: string) => {
    if (!h) return null; const v = h.v[k] as (number | null)[]; const n = v.length;
    const a = v[n - 1], b = v[Math.max(0, n - 11)]; return a != null && b != null ? a - b : null;
  };
  return (
    <div className="stack">
      <Panel>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div><h2>#{w.id} {(w.event || "Health event").replace("EVENT: ", "")}</h2>
            <div className="muted">{w.astronaut} · {systemOf(w.event)} · detected {relT(w.opened, t0)} ({fmt(w.minutes_since, 0)} min ago)</div></div>
          <div className="row"><LevelPill level={w.level} /><Status s={STATUS_S[w.status] ?? "unknown"} text={w.status} />{w.escalated && <span className="pill s-elevated"><i />escalated</span>}</div>
        </div>
        <div className="row mt">
          <button className="btn danger" disabled={closed || w.acknowledged || !!busy} onClick={() => act("acknowledge", "alert acknowledged")}>{w.acknowledged ? "Acknowledged ✓" : "Acknowledge alert"}</button>
          <button className="btn" disabled={closed || !!busy} onClick={() => act("request_measurements", "extra measurements requested")}>Request measurements</button>
          <button className="btn" disabled={closed || !!busy || !w.requests.length} onClick={() => act("verify_confirmed", "reading confirmed")} title="After re-measuring">Reading confirmed</button>
          <button className="btn" disabled={closed || !!busy || !w.requests.length} onClick={() => act("verify_sensor_issue", "sensor problem recorded")}>Sensor problem</button>
          <button className="btn" disabled={closed || !!busy || step("notify")?.state === "done"} onClick={() => act("notify_crew", "crew and medical officer notified")}>Mark crew notified</button>
          <button className="btn" disabled={closed || !!busy} onClick={() => act("start_followup", "follow-up monitoring started")}>Start follow-up monitoring</button>
          <button className="btn warn" disabled={closed || !!busy || w.level >= 3} onClick={() => { const n = prompt("Reason for escalation (optional)") ?? undefined; act("escalate", "incident escalated", n); }}>Escalate</button>
          <button className="btn" disabled={closed || !!busy} onClick={() => act("queue_earth", "report queued for Earth")}>Queue report for Earth</button>
          <button className="btn cyan" onClick={download}>Generate report ↓</button>
          <button className="btn" disabled={closed || !!busy || step("close")?.state !== "ready" && w.closed === null} onClick={() => { const n = prompt("Review note (who reviewed, outcome)") ?? undefined; act("close", "incident closed after review", n); }}
            title="Allowed once readings are back to normal">Close after review</button>
        </div>
      </Panel>
      <Panel title="Emergency workflow" info="workflow">
        <div className="wf">{w.steps.map((st: any, i: number) => (
          <div key={st.key} className={`wf-step ${st.state}`}><span className="n">{String(i + 1).padStart(2, "0")} · {st.state}</span><b>{st.label}</b><small>{st.detail}</small>
            {st.t != null && <small className="muted">{relT(st.t, t0)} · {st.by}</small>}</div>))}</div>
      </Panel>
      <div className="grid g2">
        <Panel title="What happened and why ARES raised it">
          <ul style={{ margin: 0, paddingLeft: 18, color: "var(--ink-2)" }}>{(rep.reasons || []).slice(0, 8).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          <div className="kv1 mt"><span>Detection confidence</span><b>{rep.detection_confidence ? `${rep.detection_confidence.label} (${rep.detection_confidence.score})` : "—"}</b></div>
          <div className="kv1"><span>Sensor reliability</span><b>{trig.length ? `signal quality ${trig.map((m) => m.signal_quality).join(", ")}` : "—"}</b></div>
          {rep.model_outputs && <>
            <div className="kv1"><span>Unusual-pattern score (AI)</span><b className="num">{rep.model_outputs.anomaly_score ?? "—"}</b></div>
            <div className="kv1"><span>30-min risk estimate (AI)</span><b className="num">{rep.model_outputs.risk_forecast_30min ?? "—"}</b></div></>}
          {rep.potential_risk_category && <div className="note">Possible category (a hypothesis, not a diagnosis): {rep.potential_risk_category.join("; ")}</div>}
        </Panel>
        <Panel title="Recent readings (last 3 hours)">
          {h && plotKeys.length > 0 ? <Plot className="plot sm" data={plotKeys.map((k, i) => ({
            x: h.t.map((t: number) => (t - t0) / 60), y: h.v[k], mode: "lines", name: k, line: { width: 2, color: ["#3fd8ff", "#ff8a3d", "#3b82ff"][i] } }))}
            layout={PLOT_LAYOUT({ showlegend: true, legend: { orientation: "h", y: 1.18, x: 0 }, margin: { l: 34, r: 6, t: 18, b: 22 }, xaxis: { gridcolor: "rgba(110,170,255,.08)", ticksuffix: " h" } })} />
            : <div className="empty">No individual readings for this event.</div>}
        </Panel>
      </div>
      <Panel title="Measurements that triggered the alert" info="measurements">
        {trig.length ? <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Measurement</th><th className="r">Value</th><th className="r">Usual</th><th className="r">Normal range</th><th className="r">z</th><th className="r">Lasting</th><th className="r">Change (10 min)</th><th className="r">Signal quality</th></tr></thead>
          <tbody>{trig.map((m: any) => { const k = keyOf(m.parameter); const rt = k ? rate(k) : null; return (
            <tr key={m.parameter}><td>{m.parameter}<span className="sub">{m.source}</span></td><td className="r">{m.value} {m.unit}</td><td className="r">{m.personal_expected}</td>
              <td className="r">{m.personal_band_2sd.join(" – ")}</td><td className="r">{m.z ?? "—"}</td><td className="r">{m.sustained_min} min</td>
              <td className="r">{rt == null ? "—" : `${rt >= 0 ? "+" : ""}${fmt(rt, 1)}`}</td><td className="r">{m.signal_quality}</td></tr>); })}</tbody></table></div>
          : <div className="empty">Environmental event — no individual measurements.</div>}
      </Panel>
      <Panel title="Guidance for this event"><Guidance g={g} /></Panel>
      <Panel title="Event timeline">
        <div className="tl">{w.timeline.map((e: any, i: number) => (
          <div key={i} className={`tl-item ${e.actor === "crew" ? "crew" : e.kind}`}><span className="t">{relT(e.t, t0)}</span><b style={{ fontWeight: 500 }}>{e.actor === "crew" ? "Crew" : "ARES"}</b> — {e.text}</div>))}</div>
      </Panel>
    </div>
  );
}

export default function Emergency() {
  const { s } = useApp();
  const { data } = usePoll<any>("/api/emergencies", 1500);
  const { data: mission } = usePoll<any>("/api/mission", 2000);
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => { if (data && sel === null && data.incidents.length) setSel(data.incidents[0].id); }, [data, sel]);
  if (!data) return <div className="loading">Loading emergencies…</div>;
  const t0 = data.t0, act = data.incidents.filter((i: any) => i.status === "active"), sync = data.sync;
  return (
    <>
      <div className="page-head"><div><h1>Emergency Command</h1>
        <p>Onboard medical emergency management. Works the same during an Earth blackout: every step happens here, and reports wait safely in the queue.</p></div>
        <div className="row"><span className={`link-state link-${data.comm_mode}`}>EARTH {data.comm_mode.toUpperCase()}</span>
          <span className="pill"><i style={{ background: "var(--critical)" }} />{act.length} active</span>
          <span className="pill"><i style={{ background: "var(--blue)" }} />{sync.queued} report(s) waiting{sync.critical_queued ? ` · ${sync.critical_queued} critical` : ""}</span></div></div>
      {data.comm_mode === "blackout" && <div className="banner">Earth link is DOWN. ARES is operating autonomously: follow the onboard workflow; reports are stored and will send automatically when the link returns.</div>}
      <div className="grid" style={{ gridTemplateColumns: "320px minmax(0,1fr)" }}>
        <Panel title="Health events" info="incidents">
          <div className="list">{data.incidents.length ? data.incidents.map((i: any) => (
            <div key={i.id} className={`li l${i.status === "active" ? i.level : 0} ${i.id === sel ? "sel" : ""}`} onClick={() => setSel(i.id)}>
              <div className="row" style={{ justifyContent: "space-between" }}><b>#{i.id} {i.astronaut}</b><LevelPill level={i.status === "active" ? i.level : 0} text={i.status === "active" ? undefined : i.status === "closed" ? "Closed" : "Resolved"} /></div>
              <div className="muted" style={{ fontSize: 12 }}>{systemOf(i.event)} · {relT(i.opened, t0)} · {fmt(i.minutes_since, 0)} min ago</div>
              <div className="muted" style={{ fontSize: 12 }}>{i.status}{i.acknowledged ? " · acknowledged" : ""}{i.escalated ? " · escalated" : ""}</div>
            </div>)) : <div className="empty">No health events this session. Start a scenario in Mission Simulation to see ARES respond.</div>}</div>
        </Panel>
        {sel !== null ? <Detail id={sel} t0={t0} /> : <Panel><div className="empty">Select a health event.</div></Panel>}
      </div>
      <Panel className="mt" title="Earth message queue" info="queue" right={<span className="muted" style={{ fontSize: 12 }}>{sync.policy}</span>}>
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th className="r">#</th><th>Priority</th><th>Type</th><th>Summary</th><th>Status</th><th>Waiting because</th><th className="r">Created</th><th className="r">Arrives Earth</th></tr></thead>
          <tbody>{(mission?.comms ?? s.comms).map((m: any) => (
            <tr key={m.id}><td className="r">{m.id}</td><td><span className={`pill ${m.priority === 1 ? "s-critical" : m.priority === 2 ? "s-elevated" : "s-normal"}`}><i />P{m.priority}</span></td>
              <td className="nowrap">{m.kind.replace(/_/g, " ")}</td><td>{m.summary}</td><td className="nowrap">{m.status.replace(/_/g, " ")}</td><td className="muted">{m.waiting_note ?? "—"}</td>
              <td className="r">{relT(m.created_min, t0)}</td><td className="r">{m.arrive_min == null ? "—" : relT(m.arrive_min, t0)}</td></tr>))}</tbody>
        </table></div>
      </Panel>
    </>
  );
}
