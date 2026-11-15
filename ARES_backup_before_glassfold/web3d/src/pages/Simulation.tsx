import { useEffect, useState } from "react";
import { useApp } from "../App";
import { fmt, postJSON, relT, usePoll } from "../api";
import { DataTag, LevelPill, Panel, useToast } from "../ui";

export default function Simulation() {
  const { s, aid, go } = useApp();
  const toast = useToast();
  const { data: sim, reload } = usePoll<any>("/api/simulation", 1000);
  const [key, setKey] = useState("respiratory");
  const [target, setTarget] = useState<string>(aid ?? "AST-1");
  const [speed, setSpeed] = useState<number | null>(null);
  useEffect(() => { if (sim?.scenario && sim.state !== "idle") setKey(sim.scenario); }, [sim?.scenario]);
  if (!sim) return <div className="loading">Loading simulation…</div>;
  const scen = sim.scenarios.find((x: any) => x.key === key);
  const sp = speed ?? scen?.speed ?? 4;
  const call = async (action: string, body: any = {}, msg?: string) => {
    try { await postJSON(`/api/simulation/${action}`, body); if (msg) toast(msg); reload(); }
    catch (e) { toast(`${action} failed: ${(e as Error).message}`, "err"); }
  };
  const st = sim.state;
  const running = st === "running", paused = st === "paused";
  const t0 = s.t - s.demo_minute;
  const tgtName = s.crew.find((c: any) => c.id === (sim.target ?? target))?.name;
  return (
    <>
      <div className="page-head"><div><h1>Mission Simulation</h1>
        <p>Run a scripted Mars-cruise situation through the <b>real</b> ARES engine: readings change, the AI detects, the hologram and Emergency Command respond, and reports queue for Earth. All data here are simulated.</p></div>
        <div className="row"><span className={`sim-state sim-${st}`}>{st}</span><DataTag kind="sim" /></div></div>
      {st === "resetting" && <div className="banner info">Resetting: rebuilding the crew's personal baselines from scratch ({sim.reset_seconds ?? 0} s, about 15 s)…</div>}
      {sim.error && <div className="banner">{sim.error}</div>}
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.25fr) minmax(0,1fr)" }}>
        <Panel title="1 · Choose a scenario" info="scenarios">
          <div className="scen-grid">{sim.scenarios.map((x: any, i: number) => (
            <button key={x.key} className={`scen ${key === x.key ? "on" : ""}`} onClick={() => { setKey(x.key); setSpeed(null); }} disabled={st === "resetting"}>
              <b>{i + 1}. {x.title}</b><p>{x.summary}</p>
              <p className="muted" style={{ marginTop: 4 }}>{x.duration_min >= 1440 ? `${(x.duration_min / 1440).toFixed(0)} days` : `${x.duration_min} min`} of mission time · default {x.speed}× speed</p>
            </button>))}</div>
        </Panel>
        <div className="stack">
          <Panel title="2 · Controls">
            <div className="row">
              <label className="field">Astronaut<select value={target} onChange={(e) => setTarget(e.target.value)} disabled={running || paused}>
                {s.crew.map((c: any) => <option key={c.id} value={c.id}>{c.name} — {c.role}</option>)}</select></label>
              <label className="field" style={{ flex: 1 }}><span>Speed: <b>{sp}</b> mission-minutes per second</span>
                <input type="range" min={1} max={60} value={sp} onChange={(e) => { setSpeed(+e.target.value); if (running) call("speed", { speed: +e.target.value }); }} /></label>
            </div>
            <div className="row mt">
              <button className="btn primary" disabled={st === "resetting"} onClick={() => call("start", { scenario: key, astronaut_id: target, speed: sp }, `Started: ${scen?.title}`)}>
                {running || paused ? "Restart with this scenario" : "Start simulation"}</button>
              <button className="btn" disabled={!running} onClick={() => call("pause", {}, "Paused — mission clock stopped")}>Pause</button>
              <button className="btn" disabled={!paused} onClick={() => call("resume", {}, "Resumed")}>Resume</button>
              <button className="btn warn" disabled={!(running || paused || st === "completed")} onClick={() => call("stop", {}, "Stopped — scenarios cleared")}>Stop</button>
              <button className="btn danger" disabled={st === "resetting"} onClick={() => { if (confirm("Reset the whole mission to its initial state? Health history from this session is cleared.")) call("reset", {}, "Reset started"); }}>Reset</button>
            </div>
            {st === "stopped" && <div className="row mt"><span className="muted">Clock is paused.</span><button className="btn sm" onClick={async () => { await postJSON("/api/speed", { minutes_per_second: 2, paused: false }); toast("Clock running (nominal)"); }}>Resume nominal clock</button></div>}
          </Panel>
          <Panel title="3 · Progress">
            {sim.title ? <>
              <div className="row" style={{ justifyContent: "space-between" }}><b>{sim.title}</b><span className="muted">target: {sim.target_name}</span></div>
              <div className="progress mt"><i style={{ width: `${Math.round((sim.progress ?? 0) * 100)}%` }} /></div>
              <div className="row muted" style={{ fontSize: 12, marginTop: 4 }}><span>{fmt(sim.elapsed_min, 0)} / {sim.duration_min} mission minutes</span><span>· clock {sim.clock_paused ? "paused" : `${sim.speed}×`}</span></div>
              <h4>Script</h4>
              {sim.steps.map((x: any, i: number) => <div key={i} className="kv1"><span>{x.done ? "✓" : "○"} at T+{x.at_min} min</span><b>{x.text}</b></div>)}
              <div className="note">What to watch: {sim.scenarios.find((x: any) => x.key === sim.scenario)?.watch}</div>
              <div className="row"><button className="btn sm cyan" onClick={() => go("body")}>Watch the hologram →</button><button className="btn sm" onClick={() => go("emergency")}>Emergency Command →</button><button className="btn sm" onClick={() => go("crew")}>Crew health →</button></div>
            </> : <div className="empty">No scenario running. Pick one and press Start.</div>}
          </Panel>
        </div>
      </div>
      <div className="grid g3 mt">
        <Panel title="Crew right now">
          {s.crew.map((c: any) => <div key={c.id} className="kv1"><span>{c.name}{c.id === sim.target ? " (target)" : ""}</span>
            <b><span className="num" style={{ marginRight: 8 }}>HR {fmt(c.values.hr, 0)} · SpO₂ {fmt(c.values.spo2, 0)}%</span><LevelPill level={c.level} /></b></div>)}
          <div className="kv1"><span>Open health events</span><b>{s.incidents.filter((i: any) => i.closed === null).length}</b></div>
          <div className="kv1"><span>Earth link</span><b><span className={`link-state link-${s.mission.comm_mode}`}>{s.mission.comm_mode.toUpperCase()}</span></b></div>
          <div className="kv1"><span>Reports waiting for Earth</span><b>{s.comms_pending}</b></div>
        </Panel>
        <Panel title="Simulation events">
          <div className="log">{sim.events.length ? sim.events.map((e: any, i: number) => <div key={i} className="logline"><span className="t">{relT(e.t, t0)}</span><span>{e.text}</span></div>) : <div className="empty">No simulation events yet.</div>}</div>
        </Panel>
        <Panel title="Manual mission controls">
          <div className="field">Earth link override</div>
          <div className="seg" style={{ marginBottom: 10 }}>{[["", "Auto"], ["connected", "Connected"], ["delay", "Delay"], ["blackout", "Blackout"]].map(([m, l]) => (
            <button key={m} className={(s.mission.comm_reason === "operator override" ? s.mission.comm_mode : "") === m ? "on" : ""}
              onClick={async () => { await postJSON("/api/comm", { mode: m || null }); toast(`Earth link: ${l}`); }}>{l}</button>))}</div>
          <div className="row"><button className="btn sm" onClick={async () => { await postJSON("/api/shelter", { on: !s.shelter }); toast(s.shelter ? "Crew left storm shelter" : "Crew in storm shelter"); }}>{s.shelter ? "Leave storm shelter" : "Enter storm shelter"}</button></div>
          <h4>Inject a single event (advanced)</h4>
          <div className="row"><select id="oneScen" defaultValue="spo2_drop">{s.scenarios.map((x: any) => <option key={x.key} value={x.key}>{x.name}</option>)}</select>
            <button className="btn sm" onClick={async () => { const k = (document.getElementById("oneScen") as HTMLSelectElement).value;
              try { const r = await postJSON("/api/scenario", { key: k, astronaut_id: target }); toast(`Injected: ${r.scenario} → ${s.crew.find((c: any) => c.id === target)?.name}`); } catch (e) { toast(String(e), "err"); } }}>Inject → {tgtName}</button>
            <button className="btn sm ghost" onClick={async () => { await postJSON("/api/clear", {}); toast("All injected events cleared"); }}>Clear all</button></div>
        </Panel>
      </div>
    </>
  );
}
