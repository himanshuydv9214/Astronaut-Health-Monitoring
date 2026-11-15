import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../App";
import { fmt, getJSON, relT, STATE_COLOR, STATE_LABEL, useAnatomy, usePoll, type RegionState } from "../api";
import Guidance from "../components/Guidance";
import Hologram, { MODES, type LayerKey, type ViewKey } from "../components/Hologram";
import { InfoButton, Spark, Status } from "../ui";

const KIND: Record<string, string> = {
  measured: "Measured by a body sensor", lab_marker: "Blood-test marker (not imaging)", functional: "Brain function (alertness tests), not a brain scan",
  exposure: "Radiation exposure (no organ injury implied)", organism_evidence: "NASA mouse research — not this astronaut", environmental: "Likely caused by cabin air",
  none: "Shown for anatomy only",
};

function RegionPanel({ id, info, meta, aid, s, focus }: any) {
  const { data: g } = usePoll<any>(id ? `/api/medical-guidance?astronaut=${aid}&region=${id}` : null, 4000);
  if (!meta) return (
    <div className="empty" style={{ padding: 4 }}>
      <h2 style={{ marginBottom: 6, color: "var(--ink)" }}>Select a body region</h2>
      Click any glowing structure. Colours come only from ARES findings; a region without a sensor is labelled “No sensor here” rather than shown as normal.
      <ul style={{ marginTop: 10 }}><li>Drag to rotate · scroll to zoom · right-drag to pan</li><li>Use the mode buttons for organs, blood vessels or skeleton</li></ul>
    </div>);
  const st: RegionState = info?.state ?? "not_monitored";
  const rec = s.detail.recent;
  const conf = focus?.region === id ? focus.confidence_label + ` (${focus.confidence})` : s.detail.classification.confidence_label;
  const alert = ["observation", "elevated", "critical"].includes(st);
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div><h2>{meta.label}</h2><div className="muted">{meta.system} system · BodyParts3D anatomy</div></div><Status s={st} />
      </div>
      {info && <div className="row" style={{ margin: "8px 0" }}><span className="tag meas">{KIND[info.kind] ?? info.kind}</span><span className="tag sim">{info.category}</span></div>}
      {info?.note && <div className="note">{info.note}</div>}
      {info?.metrics?.length > 0 && <h4>Current measurements vs this astronaut's normal</h4>}
      {info?.metrics?.map((m: any) => (
        <div key={m.key} className="panel" style={{ padding: "8px 10px", marginBottom: 6 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span>{m.label} <span className={`tag ${m.source === "measured" ? "meas" : "meas derived"}`}>{m.source}</span></span>
            <b className="num" style={{ fontSize: 16 }}>{m.value ?? "—"} <span className="muted" style={{ fontSize: 12 }}>{m.unit}</span></b>
          </div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="muted" style={{ fontSize: 12 }}>usual {m.expected ?? "—"} · range {m.band ? `${m.band[0]}–${m.band[1]}` : "—"} · {m.z == null ? "" : `${Math.abs(m.z).toFixed(1)}× normal variation`}</span>
            {rec.v[m.key] && <Spark values={rec.v[m.key].slice(-150)} lo={m.band?.[0]} hi={m.band?.[1]} w={130} h={28}
              color={m.sev >= 2 ? STATE_COLOR.elevated : m.sev === 1 ? STATE_COLOR.observation : STATE_COLOR.normal} />}
          </div>
        </div>))}
      {info && <>
        <h4>AI findings</h4>
        <ul style={{ margin: 0, paddingLeft: 18, color: "var(--ink-2)" }}>{info.evidence.length ? info.evidence.map((e: string, i: number) => <li key={i}>{e}</li>) : <li>No deviation from this astronaut's normal.</li>}</ul>
        <div className="kv1"><span>Detection confidence</span><b>{conf}</b></div>
        {info.projected_state && info.projected_state !== st && <div className="kv1"><span>If the trend continues (30 min)</span><b>{STATE_LABEL[info.projected_state]}</b></div>}
      </>}
      {info?.research_evidence?.length > 0 && <>
        <h4>Spaceflight research evidence (mice — not this astronaut)</h4>
        <ul style={{ margin: 0, paddingLeft: 18, color: "var(--ink-2)" }}>{info.research_evidence.map((r: any, i: number) => <li key={i}><b>{r.title}</b> — {r.summary} <span className="muted">[{r.dataset}]</span></li>)}</ul>
      </>}
      {(alert || info?.research_evidence?.length || ["kidney_left", "kidney_right", "liver"].includes(id)) && <div className="mt"><Guidance g={g} compact /></div>}
      {!alert && !info?.research_evidence?.length && info?.state === "normal" && <p className="muted mt">No health concern for this region right now — nothing to advise.</p>}
    </div>
  );
}

export default function BodyPage() {
  const { s, aid, meta, glow, setGlow } = useApp();
  const { data: anat, live } = useAnatomy(aid);
  const [mode, setMode] = useState("hologram");
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>(MODES.hologram.layers);
  const [skin, setSkin] = useState(1);
  const [sel, setSel] = useState<string | null>(null);
  const [hov, setHov] = useState<string | null>(null);
  const [iso, setIso] = useState(false);
  const [view, setView] = useState<{ key: ViewKey; region?: string; nonce: number }>({ key: "reset", nonce: 0 });
  const [compare, setCompare] = useState<"current" | "baseline" | "projected">("current");
  const [ev, setEv] = useState(false);
  const [rad, setRad] = useState(false);
  const [hist, setHist] = useState<any>(null);
  const [tIdx, setTIdx] = useState<number | null>(null);
  useEffect(() => {
    if (!aid) return;
    let alive = true;
    const load = () => getJSON(`/api/anatomy/history?astronaut=${aid}&minutes=480`).then((h) => alive && setHist(h)).catch(() => {});
    load(); const i = setInterval(load, 6000);
    return () => { alive = false; clearInterval(i); };
  }, [aid]);
  const pick = (m: string) => { setMode(m); setLayers(MODES[m].layers); if (m !== "hologram") setIso(false); };
  // emergency auto-focus: a NEW incident at level >= 2 flies the camera to the affected organ
  const lastInc = useRef<number | null>(null);
  useEffect(() => {
    const f = anat?.focus;
    if (!f || f.incident_id == null || f.level < 2 || lastInc.current === f.incident_id) return;
    lastInc.current = f.incident_id;
    setSel(f.region); setTIdx(null); setCompare("current"); pick("hologram"); setSkin(0.35);
    setView({ key: "focus", region: f.region, nonce: Date.now() });
  }, [anat?.focus]);
  useEffect(() => { lastInc.current = null; setSel(null); }, [aid]);
  const regions = anat?.regions ?? {};
  const frame = tIdx !== null ? hist?.frames[tIdx]?.regions ?? null : null;
  const cmp = useMemo(() => {
    if (frame) return frame;
    if (compare === "current") return null;
    const o: Record<string, RegionState> = {};
    for (const [k, r] of Object.entries<any>(regions)) o[k] = compare === "baseline" ? (r.state === "not_monitored" ? "not_monitored" : "normal") : (r.projected_state ?? r.state);
    return o;
  }, [frame, compare, regions]);
  const counts: Record<string, number> = {};
  for (const r of Object.values<any>(cmp ?? Object.fromEntries(Object.entries<any>(regions).map(([k, v]) => [k, v.state])))) counts[r as string] = (counts[r as string] ?? 0) + 1;
  const metaById = Object.fromEntries(meta.map((m: any) => [m.id, m]));
  const ov = anat?.overlays;
  const nF = hist?.frames.length ?? 0;
  return (
    <>
      <div className="page-head"><div><h1>3D Health Hologram <InfoButton k="body" /></h1>
        <p>{s.detail.profile.name}: every highlight is a live ARES finding mapped to the body system it concerns. Live via {live === "ws" ? "WebSocket" : live === "poll" ? "polling" : "—"}.</p></div>
        <div className="row">
          {(Object.keys(MODES)).map((k) => <button key={k} className={`btn sm ${mode === k ? "on" : ""}`} onClick={() => pick(k)}>{MODES[k].label}</button>)}
        </div></div>
      <div className="body-layout">
        <div className="holo-stage">
          {meta.length > 0 && <Hologram meta={meta} states={regions} frameStates={cmp} layers={layers} heartInVascular={MODES[mode]?.heartInVascular}
            skinOpacity={skin} selected={sel} hovered={hov} isolate={iso} onHover={setHov} onSelect={(id) => { setSel(id); if (!id) setIso(false); }}
            view={view} glow={glow} showEvidence={ev} radiation={rad && ov ? { intensity: Math.max(0.15, ov.radiation.intensity), spe: ov.radiation.spe_active } : null} />}
          <div className="holo-hud">
            <span className="corner a" /><span className="corner b" /><span className="corner c" /><span className="corner d" />
            <div className="holo-tl">
              <div className="hud-box"><div className="ttl">Layers</div>
                <div className="stack" style={{ gap: 4 }}>
                  {(["skin", "organs", "vessels", "skeleton", "muscles"] as LayerKey[]).map((k) => (
                    <label key={k} className="row" style={{ gap: 6, cursor: "pointer" }}><input type="checkbox" checked={layers[k]} onChange={() => { setMode("custom"); setLayers((l) => ({ ...l, [k]: !l[k] })); }} />
                      {{ skin: "Skin (hologram shell)", organs: "Organs", vessels: "Blood vessels", skeleton: "Skeleton", muscles: "Muscles" }[k]}</label>))}
                  <label className="row" style={{ gap: 6 }}>Skin <input type="range" min={0.1} max={1.6} step={0.05} value={skin} onChange={(e) => setSkin(+e.target.value)} style={{ width: 90 }} /></label>
                </div></div>
              <div className="hud-box"><div className="ttl">Status</div><div className="legend">
                {(["normal", "observation", "elevated", "critical", "unknown", "not_monitored"]).map((k) => (
                  <span key={k}><i style={{ background: STATE_COLOR[k] }} />{STATE_LABEL[k]} <b>{counts[k] ?? 0}</b></span>))}
                <span><i style={{ background: "#ff7c7c" }} />Arteries <span className="muted">(anatomy)</span></span>
                <span><i style={{ background: "#5b8cff" }} />Veins <span className="muted">(anatomy)</span></span>
              </div></div>
            </div>
            <div className="holo-tr">
              <div className="row">
                {(["front", "back", "left", "right"] as ViewKey[]).map((v) => <button key={v} className="btn sm" onClick={() => setView({ key: v, nonce: Date.now() })} style={{ textTransform: "capitalize" }}>{v}</button>)}
                <button className="btn sm" onClick={() => { setIso(false); setSel(null); setView({ key: "reset", nonce: Date.now() }); }}>Reset camera</button>
              </div>
              <div className="row">
                {(["current", "baseline", "projected"] as const).map((c) => <button key={c} className={`btn sm ${compare === c && tIdx === null ? "on" : ""}`} onClick={() => { setCompare(c); setTIdx(null); }}>
                  {{ current: "Now", baseline: "Personal normal", projected: "If trend continues (+30 min)" }[c]}</button>)}
              </div>
              <div className="row">
                <button className={`btn sm ${ev ? "on" : ""}`} onClick={() => setEv((x) => !x)} title="NASA mouse spaceflight findings on muscles and bones">Research evidence</button>
                <button className={`btn sm ${rad ? "on" : ""}`} onClick={() => setRad((x) => !x)}>Radiation exposure</button>
                <button className={`btn sm ${glow ? "on" : ""}`} onClick={() => setGlow(!glow)} title="Turn off for slower computers">Glow</button>
              </div>
              {sel && <div className="row">
                <button className={`btn sm ${iso ? "on" : ""}`} onClick={() => setIso((x) => !x)}>{iso ? "Show all" : "Isolate selected"}</button>
                <button className="btn sm cyan" onClick={() => { setSkin((x) => Math.min(x, 0.45)); setView({ key: "focus", region: sel, nonce: Date.now() }); }}>Focus on selected</button></div>}
              {hov && metaById[hov] && <div className="hud-box">{metaById[hov].label} · {STATE_LABEL[(cmp?.[hov] ?? regions[hov]?.state ?? "not_monitored") as string]}</div>}
            </div>
            <div className="holo-bl">
              <div className="hud-box" style={{ flex: 1, minWidth: 300 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="ttl" style={{ margin: 0 }}>Timeline</span>
                  <span className="muted" style={{ fontSize: 12 }}>{tIdx !== null && hist ? `History · ${relT(hist.frames[tIdx].t, s.t - s.demo_minute)} · ${hist.frames[tIdx].ctx}` : "Live"}</span>
                  <button className={`btn sm ${tIdx === null ? "on" : ""}`} onClick={() => setTIdx(null)}>Live</button>
                </div>
                <input type="range" min={0} max={Math.max(nF - 1, 0)} value={tIdx ?? Math.max(nF - 1, 0)} style={{ width: "100%" }}
                  onChange={(e) => { const v = +e.target.value; setTIdx(v >= nF - 1 ? null : v); }} aria-label="Timeline" />
              </div>
              {rad && ov && <div className="hud-box" style={{ maxWidth: 360 }}><b>Radiation (exposure, not injury)</b><br />
                <span className="num">{fmt(ov.radiation.dose_rate_msv_day, 2)} mSv/day · career {fmt(ov.radiation.career_total_msv, 0)} mSv ({fmt(ov.radiation.pct_career_limit, 0)}% of limit)</span></div>}
            </div>
          </div>
        </div>
        <aside className="panel side-panel">
          <RegionPanel id={sel} info={sel ? regions[sel] : null} meta={sel ? metaById[sel] : null} aid={aid} s={s} focus={anat?.focus} />
          {ov && <div className="mt" style={{ borderTop: "1px solid var(--line)", paddingTop: 8 }}>
            <h4 style={{ marginTop: 0 }}>Whole-body (not tied to one organ)</h4>
            <div className="kv1"><span>Body temperature (estimated)</span><b className="num">{ov.systemic_temperature.metric?.value ?? "—"} °C</b></div>
            <div className="kv1"><span>Immune blood tests</span><b>{ov.immune_labs.flags.length ? ov.immune_labs.flags.join(", ") : "within range"}</b></div>
          </div>}
        </aside>
      </div>
    </>
  );
}
