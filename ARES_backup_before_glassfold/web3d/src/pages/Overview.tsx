import { useApp } from "../App";
import { CONTEXT, fmt, LEVEL, relT, STATE_COLOR, useAnatomy, VITALS } from "../api";
import Hologram from "../components/Hologram";
import { LevelPill, Panel, Plot, PLOT_LAYOUT } from "../ui";

export function CrewCards() {
  const { s, aid, setAid, go } = useApp();
  return (
    <div className="crew-cards">
      {s.crew.map((c: any) => (
        <div key={c.id} className={`panel crew-card lvl-${c.level} ${c.id === aid ? "sel" : ""}`} onClick={() => setAid(c.id)}
          onDoubleClick={() => { setAid(c.id); go("crew"); }} title="Click to select · double-click for full health profile">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div><div className="nm">{c.name}</div><div className="rl">{c.role} · {CONTEXT[c.context] ?? c.context}</div></div>
            <LevelPill level={c.level} />
          </div>
          <div className="vgrid">
            {VITALS.map(([k, lab, u, dp]) => {
              const v = c.values[k], z = c.z[k];
              return <div key={k} className={`vcell ${v === null ? "na" : Math.abs(z ?? 0) >= 3 ? "dev" : ""}`}>
                <b>{fmt(v, dp)}</b><span>{lab} · {u}</span></div>;
            })}
          </div>
          <div className="row">
            <span className={`pill ${c.sensor_health === "OK" ? "s-good" : "s-unknown"}`}><i />Sensors {c.sensor_health === "OK" ? "OK" : c.sensor_health}</span>
            <span className={`pill s-${s.behavioral[c.id]?.level ? "observation" : "good"}`}><i />Alertness {s.behavioral[c.id]?.label ?? "—"}</span>
            {c.post_event && <span className="pill s-observation"><i />Follow-up monitoring</span>}
          </div>
        </div>))}
    </div>
  );
}

export default function Overview() {
  const { s, aid, go, meta, glow } = useApp();
  const { data: anat } = useAnatomy(aid);
  const m = s.mission;
  const sel = s.crew.find((c: any) => c.id === aid) ?? s.crew[0];
  const openInc = s.incidents.filter((i: any) => i.closed === null);
  const who = (a: string) => s.crew.find((c: any) => c.id === a)?.name ?? (a === "ENV" ? "Radiation environment" : a === "CABIN" ? "Cabin air" : a);
  const cb = s.cabin || {};
  const th = [...Array(121).keys()].map((i) => (i * Math.PI) / 60);
  const nM = (2 * Math.PI) / 686.98, mth = Math.PI - nM * m.transfer_days + nM * m.mission_day;
  return (
    <>
      <div className="page-head"><div><h1>Mission Overview</h1>
        <p>Live status of the crew, the spacecraft environment and the link to Earth. Click an astronaut to focus the hologram; double-click for their full health profile.</p></div></div>
      <CrewCards />
      <div className="grid g3 mt" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1.15fr) minmax(0,1fr)" }}>
        <div className="stack">
          <Panel title="Active health events" info="incidents" right={<button className="btn sm" onClick={() => go("emergency")}>Emergency Command →</button>}>
            <div className="list">
              {openInc.length ? openInc.map((i: any) => (
                <div key={i.id} className={`li l${i.level}`} onClick={() => go("emergency")}>
                  <div className="row" style={{ justifyContent: "space-between" }}><b>#{i.id} {who(i.astronaut_id)}</b><LevelPill level={i.level} /></div>
                  <div className="muted">{(i.event || "").replace("EVENT: ", "")} · since {relT(i.opened, s.t - s.demo_minute)}{i.acknowledged ? " · acknowledged" : ""}</div>
                </div>)) : <div className="empty">No active health events. ARES is monitoring all four crew members.</div>}
            </div>
          </Panel>
          <Panel title="Earth communication" info="comms">
            <div className="kv1"><span>Link</span><b><span className={`link-state link-${m.comm_mode}`}>{m.comm_mode.toUpperCase()}</span> {m.comm_reason || ""}</b></div>
            <div className="kv1"><span>Signal delay (one way)</span><b className="num">{fmt(m.one_way_light_time_min, 1)} min</b></div>
            <div className="kv1"><span>Earliest reply from Earth</span><b>{m.comm_mode === "blackout" ? "none (blackout)" : `${fmt(m.round_trip_min + 5, 0)} min`}</b></div>
            <div className="kv1"><span>Reports waiting to send</span><b className="num">{s.comms_pending}</b></div>
            <p className="muted" style={{ margin: "6px 0 0" }}>ARES never waits for Earth: onboard analysis continues in every link state.</p>
          </Panel>
        </div>
        <section className="panel" style={{ padding: 0, overflow: "hidden", minHeight: 520 }}>
          <div className="holo-stage" style={{ height: "100%", minHeight: 520, border: "none", borderRadius: 0 }}>
            {meta.length > 0 && <Hologram meta={meta} states={anat?.regions ?? {}} layers={{ skin: true, organs: true, vessels: true, skeleton: false, muscles: false }}
              compact glow={glow} labels radiation={anat?.overlays.radiation.spe_active ? { intensity: anat.overlays.radiation.intensity, spe: true } : null} />}
            <div className="holo-hud">
              <div className="holo-tl"><div className="hud-box"><div className="ttl">Live hologram</div><b>{sel.name}</b>
                <div style={{ marginTop: 4 }}><LevelPill level={sel.level} /></div></div></div>
              <div className="holo-bl"><span className="muted" style={{ fontSize: 12 }}>Regions light up only from ARES findings</span>
                <button className="btn sm cyan" onClick={() => go("body")}>Open interactive hologram →</button></div>
              <span className="corner a" /><span className="corner b" /><span className="corner c" /><span className="corner d" />
            </div>
          </div>
        </section>
        <div className="stack">
          <Panel title="Cabin air" info="cabin">
            {cb.current ? <>
              <div className="kv1"><span>CO₂ (1-hour average)</span><b className="num">{fmt(cb.co2_1h, 2)} mmHg</b></div>
              <div className="bar"><i style={{ width: `${Math.min(100, (100 * cb.co2_1h) / 6)}%`, background: cb.co2_1h > 3 ? STATE_COLOR.critical : cb.co2_1h > 2.5 ? STATE_COLOR.observation : STATE_COLOR.normal }} /></div>
              <div className="kv1"><span>Limit</span><b>3.0 mmHg (1 h) · 2.5 mmHg (7 days)</b></div>
              <div className="kv1"><span>Temperature / humidity</span><b className="num">{fmt(cb.current.temp_c, 1)} °C · {fmt(cb.current.rh_pct, 0)} %</b></div>
              {cb.attribution && <div className="note warn">{cb.attribution.text}</div>}
            </> : <div className="empty">Waiting for cabin data…</div>}
          </Panel>
          <Panel title="Radiation exposure" info="radiation">
            {s.spe_active && <div className="banner">Solar particle event in progress — crew {s.shelter ? "in storm shelter" : "should shelter"}</div>}
            {s.crew.map((c: any) => (
              <div key={c.id}><div className="kv1"><span>{c.name}</span><b className="num">{fmt(c.dose.career_total_msv, 0)} / {c.dose.career_limit_msv} mSv</b></div>
                <div className="bar"><i style={{ width: `${Math.min(100, c.dose.pct_career_limit)}%` }} /></div></div>))}
            <p className="muted" style={{ margin: 0, fontSize: 12 }}>Exposure only — ARES does not estimate cancer risk or organ damage.</p>
          </Panel>
        </div>
      </div>
      <div className="grid g2 mt">
        <Panel title="Where we are">
          <Plot className="plot sm" data={[
            { x: th.map(Math.cos), y: th.map(Math.sin), mode: "lines", line: { color: "rgba(63,216,255,.25)", width: 1 }, hoverinfo: "skip" },
            { x: th.map((t) => 1.524 * Math.cos(t)), y: th.map((t) => 1.524 * Math.sin(t)), mode: "lines", line: { color: "rgba(255,138,61,.3)", width: 1, dash: "dot" }, hoverinfo: "skip" },
            { x: [0], y: [0], mode: "markers+text", marker: { size: 10, color: "#f2c94c" }, text: ["Sun"], textposition: "bottom center", hoverinfo: "skip" },
            { x: [1.524 * Math.cos(mth)], y: [1.524 * Math.sin(mth)], mode: "markers+text", marker: { size: 9, color: "#ff8a3d" }, text: ["Mars"], textposition: "middle left", hoverinfo: "skip" },
            { x: [m.earth_xy_au[0]], y: [m.earth_xy_au[1]], mode: "markers+text", marker: { size: 9, color: "#3b82ff" }, text: ["Earth"], textposition: "top center", hoverinfo: "skip" },
            { x: [m.sc_xy_au[0]], y: [m.sc_xy_au[1]], mode: "markers+text", marker: { size: 10, color: "#3fd8ff", symbol: "diamond" }, text: ["ARES crew"], textposition: "top center", hoverinfo: "skip" },
            { x: [m.earth_xy_au[0], m.sc_xy_au[0]], y: [m.earth_xy_au[1], m.sc_xy_au[1]], mode: "lines", line: { color: "#3fd8ff", width: 1, dash: "dash" }, hovertemplate: `${fmt(m.one_way_light_time_min, 1)} min signal delay<extra></extra>` },
          ]} layout={PLOT_LAYOUT({ margin: { l: 4, r: 4, t: 4, b: 4 }, hovermode: "closest", xaxis: { visible: false, range: [-1.8, 1.8], scaleanchor: "y" }, yaxis: { visible: false, range: [-1.7, 1.7] } })} />
          <div className="muted" style={{ fontSize: 12 }}>Simplified Earth–Mars transfer orbit · {fmt(m.days_to_mars, 0)} days to Mars · {fmt(m.distance_au, 2)} AU from Earth</div>
        </Panel>
        <Panel title="Event log" info="log">
          <div className="log">{s.log.slice(0, 50).map((l: any, i: number) => (
            <div key={i} className={`logline l${l.level}`}><span className="t">{relT(l.t, s.t - s.demo_minute)}</span><span>{l.text}</span></div>))}</div>
        </Panel>
      </div>
    </>
  );
}

export { LEVEL };
