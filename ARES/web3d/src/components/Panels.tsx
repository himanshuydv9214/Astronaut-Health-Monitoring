import { useMemo } from "react";
import { KIND_LABEL, STATE_COLOR, STATE_LABEL, type AnatomyState, type History, type Metric, type RegionInfo,
  type RegionMeta, type RegionState } from "../api";

const LVL = ["Normal", "Observation", "Medical assessment", "Critical"];
const LVL_STATE: RegionState[] = ["normal", "observation", "elevated", "critical"];

export function StateBadge({ state, text }: { state: RegionState; text?: string }) {
  return <span className={`badge b-${state}`}><i style={{ background: STATE_COLOR[state] }} />{text ?? STATE_LABEL[state]}</span>;
}
export function CategoryChip({ category }: { category: string }) {
  const cls = category.startsWith("REAL NASA") ? "c-nasa" : category.startsWith("REAL NON") ? "c-real" :
    category.startsWith("MODEL") ? "c-model" : category.startsWith("SYNTHETIC") ? "c-syn" : "c-none";
  return <span className={`chip ${cls}`}>{category}</span>;
}

/* ------------------------------------------------------------------ left panel */
export function LeftPanel({ state, selectedAid, onAid, anatomy }: {
  state: any; selectedAid: string | null; onAid: (id: string) => void; anatomy: AnatomyState | null;
}) {
  if (!state) return <aside className="left panel"><p className="muted">Connecting to ARES…</p></aside>;
  const m = state.mission;
  const crew = state.crew as any[];
  const sel = crew.find((c) => c.id === selectedAid) ?? crew[0];
  const vit: [string, string, string, number][] = [["hr", "Heart rate", "bpm", 0], ["spo2", "SpO₂", "%", 0], ["rr", "Resp. rate", "/min", 1],
    ["sbp", "Systolic BP", "mmHg", 0], ["temp", "Core temp (est.)", "°C", 2], ["hrv_rmssd", "HRV RMSSD", "ms", 0]];
  return (
    <aside className="left panel">
      <h3>Mission</h3>
      <div className="kvs">
        <div><span>Phase</span><b>{m.phase}</b></div>
        <div><span>Mission day</span><b>{m.mission_day.toFixed(1)}</b></div>
        <div><span>Light time</span><b>{m.one_way_light_time_min.toFixed(1)} min</b></div>
        <div><span>Earth link</span><b className={`mode ${m.comm_mode}`}>{m.comm_mode.toUpperCase()}</b></div>
      </div>
      <h3>Crew</h3>
      <div className="crew-list">
        {crew.map((c) => (
          <button key={c.id} className={`crew ${c.id === sel.id ? "on" : ""}`} onClick={() => onAid(c.id)}>
            <span><b>{c.name}</b><small>{c.role}</small></span>
            <StateBadge state={LVL_STATE[c.level]} text={`L${c.level}`} />
          </button>
        ))}
      </div>
      <h3>Readings · {sel.name}</h3>
      <div className="readings">
        {vit.map(([k, lab, u, dp]) => {
          const v = sel.values[k]; const z = sel.z[k];
          const dev = z !== null && Math.abs(z) >= 3;
          return <div key={k} className={dev ? "dev" : ""}><b>{v === null ? "—" : Number(v).toFixed(dp)}</b><span>{lab} · {u}</span></div>;
        })}
      </div>
      <div className="src-line">
        <CategoryChip category="SYNTHETIC SIMULATION DATA" />
        <small className="muted">Crew are fictional; streams simulated. Context: {sel.context}. Sensors {sel.sensor_health}.</small>
      </div>
      {anatomy && <div className="link-line muted">3D link: {anatomy.comm_mode === "blackout" ? "Earth blackout — ARES operating locally" : "Earth link " + anatomy.comm_mode}</div>}
    </aside>
  );
}

/* ------------------------------------------------------------------ sparkline with personal band */
function Spark({ v, lo, hi, color }: { v: (number | null)[]; lo: (number | null)[]; hi: (number | null)[]; color: string }) {
  const W = 220, H = 44;
  const all = [...v, ...lo, ...hi].filter((x): x is number => x !== null && Number.isFinite(x));
  if (all.length < 2) return <svg width={W} height={H} />;
  const mn = Math.min(...all), mx = Math.max(...all), span = mx - mn || 1;
  const X = (i: number) => (i / Math.max(v.length - 1, 1)) * W;
  const Y = (y: number) => H - 3 - ((y - mn) / span) * (H - 6);
  const band = lo.map((l, i) => (l === null || hi[i] === null ? null : [X(i), Y(hi[i] as number), Y(l)] as const)).filter(Boolean) as [number, number, number][];
  const top = band.map(([x, yh]) => `${x},${yh}`).join(" ");
  const bot = band.slice().reverse().map(([x, , yl]) => `${x},${yl}`).join(" ");
  let d = ""; v.forEach((y, i) => { if (y === null) return; d += `${d && v[i - 1] !== null ? "L" : "M"}${X(i).toFixed(1)},${Y(y).toFixed(1)}`; });
  return (
    <svg width={W} height={H} className="spark" aria-label="trend with personal band">
      {band.length > 1 && <polygon points={`${top} ${bot}`} fill="rgba(57,135,229,.16)" />}
      <path d={d} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}

function MetricRow({ m, recent }: { m: Metric; recent: any }) {
  const series = recent?.v?.[m.key] as (number | null)[] | undefined;
  return (
    <div className="metric">
      <div className="mrow">
        <span>{m.label} <small className={m.source === "measured" ? "tag-m" : "tag-d"}>{m.source}</small></span>
        <b>{m.value === null ? "—" : m.value} <small>{m.unit}</small></b>
      </div>
      <div className="msub">
        usual {m.expected ?? "—"} · band {m.band ? `${m.band[0]}–${m.band[1]}` : "—"} · z {m.z === null ? "—" : (m.z >= 0 ? "+" : "") + m.z}
        · quality {m.quality} · trend {m.trend_per_h >= 0 ? "+" : ""}{m.trend_per_h}/h
      </div>
      {series && <Spark v={series.slice(-180)} lo={recent.lo[m.key].slice(-180)} hi={recent.hi[m.key].slice(-180)}
        color={m.sev >= 2 ? STATE_COLOR.elevated : m.sev === 1 ? STATE_COLOR.observation : STATE_COLOR.normal} />}
    </div>
  );
}

/* ------------------------------------------------------------------ organ panel */
export function OrganPanel({ meta, info, recent, compare, report }: {
  meta: RegionMeta | undefined; info: RegionInfo | undefined; recent: any; compare: string; report: any;
}) {
  if (!meta) return (
    <div className="empty">
      <h3>Select a body region</h3>
      <p className="muted">Click any organ, bone or muscle. Highlights come only from ARES findings; regions without a sensor say
        “not monitored” rather than pretending to be normal.</p>
    </div>
  );
  const state = (compare === "projected" ? info?.projected_state : compare === "baseline" ? "normal" : info?.state) ?? "not_monitored";
  return (
    <div className="organ">
      <div className="organ-head">
        <div><h2>{meta.label}</h2><small className="muted">{meta.system} · BodyParts3D mesh · {meta.triangles.toLocaleString()} triangles</small></div>
        <StateBadge state={state as RegionState} />
      </div>
      {compare !== "current" && <div className="note warn">{compare === "projected"
        ? "PROJECTED +30 min — trend extrapolation of the personal Kalman trend (MODEL-GENERATED ESTIMATE), not a forecast of diagnosis."
        : "BASELINE — the astronaut's personal expected values for the current activity context."}</div>}
      {info ? (
        <>
          <div className="chips"><span className="chip c-kind">{KIND_LABEL[info.kind]}</span><CategoryChip category={info.category} /></div>
          {info.note && <p className="note">{info.note}</p>}
          {info.metrics.length > 0 && <h4>Measurements vs personal baseline</h4>}
          {info.metrics.map((m) => compare === "baseline"
            ? <div key={m.key} className="metric"><div className="mrow"><span>{m.label}</span><b>{m.expected ?? "—"} <small>{m.unit}</small></b></div>
                <div className="msub">personal band {m.band ? `${m.band[0]}–${m.band[1]}` : "—"}</div></div>
            : <MetricRow key={m.key} m={m} recent={recent} />)}
          <h4>Evidence</h4>
          <ul className="ev">{info.evidence.length ? info.evidence.map((e, i) => <li key={i}>{e}</li>) : <li className="muted">No deviation from personal baseline.</li>}</ul>
          {info.research_evidence?.length ? (<><h4>Spaceflight research evidence (mice — not this astronaut)</h4>
            <ul className="ev">{info.research_evidence.map((r, i) => <li key={i}><b>{r.title}</b> — {r.summary} <small className="muted">[{r.dataset}]</small></li>)}</ul></>) : null}
          <h4>Recommended next assessment</h4>
          <ul className="ev">{nextSteps(info, report).map((s, i) => <li key={i}>{s}</li>)}</ul>
        </>
      ) : <p className="muted">ARES has no data mapped to this structure. Shown for anatomical context.</p>}
    </div>
  );
}

function nextSteps(info: RegionInfo, report: any): string[] {
  const steps: string[] = [];
  const protos = report?.recommended_protocols ?? [];
  if (["elevated", "critical", "observation"].includes(info.state) && protos.length) {
    protos.slice(0, 2).forEach((p: any) => steps.push(`[${p.id}] ${p.title} — ${p.steps[0]}`));
    return steps;
  }
  if (info.state === "unknown") return ["Check sensor placement / contact; re-measure with the backup device (GEN-01)."];
  if (info.kind === "lab_marker") return ["Repeat the lab test at the next opportunity; CMO review against pre-flight value."];
  if (info.kind === "functional") return ["Continue daily PVT-B and check-in; private CMO conversation if Watch persists (BEH-01)."];
  if (info.state === "not_monitored") return ["No onboard measurement for this structure — ask the crew member about symptoms if relevant."];
  return ["No action: continue routine monitoring."];
}

/* ------------------------------------------------------------------ emergency panel */
export function EmergencyPanel({ anatomy, report, comms, onAck, onClose }: {
  anatomy: AnatomyState; report: any; comms: any[]; onAck: () => void; onClose: () => void;
}) {
  const f = anatomy.focus!;
  const inc = comms.filter((c) => c.summary?.includes(`#${f.incident_id}`));
  return (
    <div className="emergency">
      <div className="em-head"><StateBadge state={LVL_STATE[f.level]} text={`L${f.level} ${LVL[f.level]}`} /><button className="x" onClick={onClose} aria-label="close">×</button></div>
      <h2>{report?.event ?? "Emergency"}</h2>
      <p className="muted">Region: <b>{f.region.replace(/_/g, " ")}</b> · incident #{f.incident_id} · detection confidence {f.confidence_label} ({f.confidence}) · sensors {f.sensor_health}</p>
      <h4>Why ARES raised this</h4>
      <ul className="ev">{(report?.reasons ?? f.reasons).slice(0, 6).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
      <h4>Approved-protocol retrieval (verbatim, DEMO knowledge base)</h4>
      {(report?.recommended_protocols ?? []).slice(0, 2).map((p: any) => (
        <div key={p.id} className="proto"><b>[{p.id}] {p.title}</b> <span className="unap">{p.approval}</span>
          <ol>{p.steps.slice(0, 5).map((s: string, i: number) => <li key={i}>{s}</li>)}</ol>
          <small className="muted">Source: {p.source?.title}</small></div>
      ))}
      <h4>Notification & Earth link</h4>
      <div className="kv1"><span>Crew notification</span><b>{report?.crew_notification ?? "—"}</b></div>
      <div className="kv1"><span>Earth priority</span><b>{report?.earth_communication_priority ?? "—"}</b></div>
      <div className="kv1"><span>Report queue</span><b>{inc.length ? inc.map((c) => `${c.status}`).join(", ") : "queued"}</b></div>
      {anatomy.comm_mode === "blackout" && <div className="note warn">Earth link in BLACKOUT: ARES continues locally; the report is stored and will be sent when the link returns.</div>}
      <div className="row"><button className="btn danger" onClick={onAck}>Acknowledge</button>
        <span className="muted">Event recorded in the tamper-evident onboard log. ARES does not diagnose or prescribe.</span></div>
    </div>
  );
}

/* ------------------------------------------------------------------ timeline */
export function Timeline({ history, idx, setIdx, t0 }: { history: History | null; idx: number | null; setIdx: (i: number | null) => void; t0: number }) {
  const n = history?.frames.length ?? 0;
  const markers = useMemo(() => {
    if (!history || n < 2) return [];
    const ta = history.frames[0].t, tb = history.frames[n - 1].t;
    return history.markers.filter((m) => m.t >= ta && m.t <= tb).map((m) => ({ ...m, x: ((m.t - ta) / Math.max(tb - ta, 1)) * 100 }));
  }, [history, n]);
  const cur = idx === null ? null : history?.frames[idx];
  const rel = (t: number) => { const mm = t - t0; const a = Math.abs(mm); return `T${mm < 0 ? "-" : "+"}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(Math.floor(a % 60)).padStart(2, "0")}`; };
  return (
    <div className="timeline">
      <div className="tl-top">
        <b>Mission timeline</b>
        <span className="muted">{cur ? `HISTORICAL · ${rel(cur.t)} · ${cur.ctx} · observed this session (synthetic crew)` : "LIVE"}</span>
        <button className={`btn sm ${idx === null ? "on" : ""}`} onClick={() => setIdx(null)}>Live</button>
      </div>
      <div className="tl-track">
        <input type="range" min={0} max={Math.max(n - 1, 0)} value={idx ?? Math.max(n - 1, 0)}
          onChange={(e) => { const v = +e.target.value; setIdx(v >= n - 1 ? null : v); }} aria-label="timeline" />
        {markers.map((m, i) => <span key={i} className={`mk mk-${m.kind}`} style={{ left: `${m.x}%` }} title={`${m.kind}: ${m.text}`} />)}
      </div>
      <div className="tl-legend muted"><span><i className="mk-observed" /> detected event (observed)</span><span><i className="mk-simulated" /> injected scenario (simulated)</span><span>Projection: use “Projected +30 min” above the body (model-generated)</span></div>
    </div>
  );
}

/* ------------------------------------------------------------------ provenance */
export function Provenance({ data, onClose }: { data: any; onClose: () => void }) {
  return (
    <div className="modal" role="dialog" aria-label="Data provenance">
      <div className="modal-card">
        <div className="em-head"><h2>Data provenance</h2><button className="x" onClick={onClose} aria-label="close">×</button></div>
        <p className="muted">Four categories, never mixed: {data?.categories?.map((c: string) => <CategoryChip key={c} category={c} />)}</p>
        {data?.results && <RealResults r={data.results} />}
        <h4>Models</h4>
        <table className="tbl"><thead><tr><th>Model</th><th>Data</th><th>Method</th><th>Validation</th><th>Status</th></tr></thead>
          <tbody>{data?.models?.map((m: any) => <tr key={m.id}><td><b>{m.id}</b> {m.name}<br /><CategoryChip category={m.category} /></td>
            <td>{m.data.join(", ")}</td><td>{m.method}</td><td>{m.validation}</td><td>{m.status}</td></tr>)}</tbody></table>
        <h4>Datasets</h4>
        <table className="tbl"><thead><tr><th>Dataset</th><th>Category</th><th>Population</th><th>Used for</th><th>Limitations</th><th>Status</th></tr></thead>
          <tbody>{data?.datasets?.map((d: any) => <tr key={d.id}><td><b>{d.id}</b><br />{d.title}<br /><small className="muted">{d.source}</small></td>
            <td><CategoryChip category={d.category} /></td><td>{d.population ?? "—"}</td><td>{d.use}</td><td>{d.limitations}</td>
            <td className={d.status.startsWith("awaiting") ? "warn-t" : ""}>{d.status}</td></tr>)}</tbody></table>
        <p className="muted">3D anatomy: {data?.anatomy_asset?.source} — {data?.anatomy_asset?.license}; {data?.anatomy_asset?.processing}.</p>
      </div>
    </div>
  );
}

function RealResults({ r }: { r: any }) {
  const d = r.model_D_radlab?.held_out, e = r.model_E_inspiration4, c = r.model_C_soleus, b = r.bone;
  const ct = b?.tibia_microct?.find((x: any) => x.parameter.startsWith("cortical_thickness"));
  const aucs = (c?.leave_one_mission_out ?? []).map((x: any) => x.auc);
  return (
    <div className="results">
      <h4>Results on real NASA data <CategoryChip category="REAL NASA DATA" /> → <CategoryChip category="MODEL-GENERATED ESTIMATES" /></h4>
      <div className="rgrid">
        {d && <div><b>Model D · ISS dosimeter vs SRAG solar events</b>
          <span>{d.strong_detected}/{d.strong_ge100pfu_evaluable} strong (≥100 pfu) 2024 events detected, held-out · {d.false_alarms_per_30d} false alarms / 30 days · naive daily mean: {d.naive_daily_mean_detected}</span>
          <small className="muted">Most SEPs are invisible inside the ISS (magnetospheric shielding); detected ones reached ISS latitudes.</small></div>}
        {e && <div><b>Model E · Inspiration4 crew labs (n = 4)</b>
          <span>Post-flight flags: generic range {e.postflight.generic_flags} vs personal baseline {e.postflight.personal_flags}; {e.postflight.generic_repeating_preflight_trait} generic flags only repeat a pre-flight trait</span>
          <small className="muted">QC excluded {e.qc_excluded_samples.length} implausible sample(s). Pre-flight false-flag rate {(e.preflight_flag_rate.generic_range * 100).toFixed(1)}% vs {(e.preflight_flag_rate.personal_baseline_loo * 100).toFixed(1)}%.</small></div>}
        {c && <div><b>Model C · mouse soleus, leave-one-mission-out</b>
          <span>AUC {Math.min(...aucs)}–{Math.max(...aucs)} across RR-1/RR-9/RR-18/Bion-M1; a single MHC IIx rule performs about as well</span>
          <small className="muted">Organism-level evidence only — never shown as astronaut risk.</small></div>}
        {ct && <div><b>Bone · RR-9 tibia microCT</b>
          <span>Cortical thickness {ct.pct_diff_vs_ground > 0 ? "+" : ""}{ct.pct_diff_vs_ground}% vs ground control (g {ct.hedges_g_vs_ground}, p {ct.p_mwu_vs_ground}, n = {ct.n_flight} vs {ct.n_ground})</span>
          <small className="muted">Full tables: reports/REAL_NASA_DATA.md</small></div>}
      </div>
    </div>
  );
}
