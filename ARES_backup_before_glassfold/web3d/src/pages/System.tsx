import { useState } from "react";
import { useApp } from "../App";
import { getJSON, postJSON, usePoll } from "../api";
import { InfoButton, Panel, Status, useToast } from "../ui";

const CAT: Record<string, string> = { "REAL NASA DATA": "real", "REAL NON-NASA BIOMEDICAL DATA": "real", "SYNTHETIC SIMULATION DATA": "sim" };

export default function System() {
  const { aid, glow, setGlow } = useApp();
  const toast = useToast();
  const { data: st } = usePoll<any>("/api/system/status", 5000);
  const { data: prov } = usePoll<any>("/api/provenance", 60000);
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any>(null);
  const [chat, setChat] = useState<any[]>([]);
  const search = async () => { if (!q.trim()) return; try { setRes(await getJSON(`/api/medical-guidance/search?q=${encodeURIComponent(q)}`)); } catch (e) { toast(String(e), "err"); } };
  const ask = async () => { if (!q.trim()) return; try { const r = await postJSON("/api/assistant", { question: q, astronaut_id: aid }); setChat((c) => [{ q, r }, ...c].slice(0, 5)); } catch (e) { toast(String(e), "err"); } };
  const r = prov?.results;
  return (
    <>
      <div className="page-head"><div><h1>Data &amp; System</h1><p>Everything ARES needs runs on this computer: database, AI models, medical knowledge base and the 3D anatomy. The internet is only used (optionally) to refresh a cached NASA solar-event list.</p></div>
        {st && <Status s={st.internet_required ? "elevated" : "good"} text={st.internet_required ? "Internet required" : "Fully offline-capable"} />}</div>
      <div className="grid g3">
        <Panel title="Offline operation">
          {st ? <>
            <div className="kv1"><span>Internet needed for monitoring</span><b>No</b></div>
            <div className="kv1"><span>Unusual-pattern model</span><b>{st.local_inference.anomaly_model ? "loaded locally" : "missing"}</b></div>
            <div className="kv1"><span>30-min risk model</span><b>{st.local_inference.risk_forecaster ? "loaded locally" : "missing"}</b></div>
            <div className="kv1"><span>Explanations (SHAP)</span><b>{st.local_inference.explanations ? "local" : "unavailable"}</b></div>
            <div className="kv1"><span>Language model</span><b style={{ maxWidth: 220 }}>{st.local_inference.language_model}</b></div>
            <div className="kv1"><span>Optional online feature</span><b>{st.optional_network_features.join("; ")}</b></div>
          </> : <div className="loading">Loading…</div>}
        </Panel>
        <Panel title="Local storage and Earth sync">
          {st ? <>
            <div className="kv1"><span>Database</span><b>SQLite, tamper-evident hash chain</b></div>
            {st.storage?.integrity && typeof st.storage.integrity === "object" && Object.entries<any>(st.storage.integrity).map(([t, v]) =>
              <div key={t} className="kv1"><span>{t}</span><b>{v.rows} rows · {v.intact ? "intact" : "TAMPERED"}</b></div>)}
            <div className="kv1"><span>Reports queued / delivered</span><b>{st.sync.queued} / {st.sync.delivered}</b></div>
            <div className="kv1"><span>Critical waiting</span><b>{st.sync.critical_queued}</b></div>
            <div className="kv1"><span>Oldest waiting</span><b>{st.sync.oldest_queued_min == null ? "—" : `${st.sync.oldest_queued_min} min`}</b></div>
            <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>{st.sync.policy}</p>
          </> : null}
        </Panel>
        <Panel title="Knowledge base and settings">
          {st ? <>
            <div className="kv1"><span>Protocols</span><b>v{st.knowledge_base.protocols.version}</b></div>
            <div className="kv1"><span>Health guidance</span><b>v{st.knowledge_base.guidance.version} · {st.knowledge_base.guidance.n_concerns} topics</b></div>
            <div className="note warn">{st.knowledge_base.protocols.status}. {st.knowledge_base.guidance.policy}</div>
            <div className="kv1"><span>Processing time per minute</span><b className="num">{st.runtime.tick_ms} ms</b></div>
            <div className="kv1"><span>Software faults contained</span><b className="num">{st.runtime.software_faults_contained}</b></div>
            <div className="kv1"><span>Hologram glow effects</span><b><button className={`btn sm ${glow ? "on" : ""}`} onClick={() => setGlow(!glow)}>{glow ? "On" : "Off (faster)"}</button></b></div>
            <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>Hardware assumption: {st.hardware_assumption}.</p>
          </> : null}
        </Panel>
      </div>
      <Panel className="mt" title="Onboard medical reference (offline search)" right={<span className="muted" style={{ fontSize: 12 }}>retrieval only — never writes new medical instructions</span>}>
        <div className="row"><input type="text" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} style={{ flex: 1, minWidth: 260 }}
          placeholder="e.g. low oxygen · fatigue · CO2 · radiation · What oxygen supplies do we have?" />
          <button className="btn primary" onClick={search}>Search procedures</button><button className="btn" onClick={ask}>Ask the onboard assistant</button></div>
        {res && <div className="grid g2 mt">
          <div><h4>Procedures</h4>{res.protocols.length ? res.protocols.map((p: any) => <div key={p.id} className="proto"><b>[{p.id}] {p.title}</b><span className="unapproved">{p.approval}</span>
            <ol>{p.steps.slice(0, 5).map((x: string, i: number) => <li key={i}>{x}</li>)}</ol><div className="src">Source: {p.source.title} · match {p.score}</div></div>) : <p className="muted">No matching procedure — ARES says so rather than guessing.</p>}</div>
          <div><h4>Health topics</h4>{res.concerns.length ? res.concerns.map((c: any) => <div key={c.concern} className="kv1"><span>{c.system}</span><b>{c.title}</b></div>) : <p className="muted">No topic matched.</p>}</div>
        </div>}
        {chat.map((c, i) => <div key={i} className="mt"><b>Q: {c.q}</b>{c.r.sections.map((sec: any, j: number) => <div key={j} className="note"><b>{sec.title}</b>
          {(sec.items || []).map((it: any, k: number) => <div key={k}>{typeof it === "string" ? `• ${it}` : `[${it.id}] ${it.title}`}</div>)}<div className="muted" style={{ fontSize: 11 }}>Source: {sec.source}</div></div>)}</div>)}
      </Panel>
      <Panel className="mt" title="Data sources and models" info="provenance">
        {r && <div className="grid g4" style={{ marginBottom: 12 }}>
          <div className="stat"><b>{r.model_D_radlab.held_out.strong_detected}/{r.model_D_radlab.held_out.strong_ge100pfu_evaluable}</b><span>Strong 2024 solar events caught on the real ISS dosimeter (held out)</span></div>
          <div className="stat"><b>{r.model_E_inspiration4.postflight.generic_repeating_preflight_trait}/{r.model_E_inspiration4.postflight.generic_flags}</b><span>Generic lab flags that only repeat an astronaut's own pre-flight value (Inspiration4)</span></div>
          <div className="stat"><b>{Math.min(...r.model_C_soleus.leave_one_mission_out.map((x: any) => x.auc))}–{Math.max(...r.model_C_soleus.leave_one_mission_out.map((x: any) => x.auc))}</b><span>Mouse soleus AUC on unseen missions</span></div>
          <div className="stat"><b>{r.bone.tibia_microct.find((x: any) => x.parameter.startsWith("cortical_thickness")).pct_diff_vs_ground}%</b><span>Tibia cortical thickness, flight vs ground mice</span></div>
        </div>}
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Dataset</th><th>Type</th><th>Population</th><th>Used for</th><th>Limitations</th><th>Status</th></tr></thead>
          <tbody>{prov?.datasets?.map((d: any) => (
            <tr key={d.id}><td><b>{d.id}</b><span className="sub">{d.title}</span></td><td><span className={`tag ${CAT[d.category] ?? "model"}`}>{d.category}</span></td>
              <td>{d.population ?? "—"}</td><td>{d.use}</td><td className="muted">{d.limitations}</td><td>{d.status}</td></tr>))}</tbody>
        </table></div>
        <p className="muted" style={{ fontSize: 12 }}>3D anatomy: {prov?.anatomy_asset?.source} — {prov?.anatomy_asset?.license}. Full results: reports/REAL_NASA_DATA.md. <InfoButton k="provenance" /></p>
      </Panel>
    </>
  );
}
