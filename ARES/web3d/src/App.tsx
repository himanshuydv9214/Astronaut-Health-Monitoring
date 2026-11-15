import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { fmt, getJSON, usePoll } from "./api";
import Alertness from "./pages/Alertness";
import BodyPage from "./pages/BodyPage";
import Crew from "./pages/Crew";
import Emergency from "./pages/Emergency";
import Insights from "./pages/Insights";
import Overview from "./pages/Overview";
import Simulation from "./pages/Simulation";
import System from "./pages/System";
import TestHistory from "./pages/TestHistory";
import { Icon, useToast } from "./ui";
import { GlassFold } from "@/components/ui/glass-fold";

export const PAGES = [
  { id: "overview", label: "Mission Overview", icon: "overview" },
  { id: "crew", label: "Crew Health", icon: "crew" },
  { id: "body", label: "3D Health Hologram", icon: "body" },
  { id: "insights", label: "Unusual Health Changes", icon: "ai" },
  { id: "emergency", label: "Emergency Command", icon: "emergency" },
  { id: "alertness", label: "Reaction Time Test", icon: "alert" },
  { id: "tests", label: "Test History", icon: "tests" },
  { id: "sim", label: "Mission Simulation", icon: "sim" },
  { id: "system", label: "Data & System", icon: "system" },
] as const;

interface Ctx { s: any; aid: string | null; setAid: (a: string) => void; go: (p: string) => void; reload: () => void; meta: any[]; glow: boolean; setGlow: (g: boolean) => void }
export const AppCtx = createContext<Ctx>(null as any);
export const useApp = () => useContext(AppCtx);

function usePage(): [string, (p: string) => void] {
  const read = () => (location.hash.replace(/^#\/?/, "") || "overview").split("?")[0];
  const [p, setP] = useState(read());
  useEffect(() => { const f = () => setP(read()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  return [p, (x: string) => { location.hash = `/${x}`; }];
}

export default function App() {
  const [page, go] = usePage();
  const [aid, setAidRaw] = useState<string | null>(() => localStorage.getItem("ares.aid"));
  const setAid = (a: string) => { setAidRaw(a); try { localStorage.setItem("ares.aid", a); } catch { /* storage off */ } };
  const { data: s, error, reload } = usePoll<any>(`/api/state${aid ? `?astronaut=${aid}` : ""}`, 1000);
  const [meta, setMeta] = useState<any[]>([]);
  const [glow, setGlowRaw] = useState(() => { try { return localStorage.getItem("ares.glow") !== "off"; } catch { return true; } });
  const setGlow = (g: boolean) => { setGlowRaw(g); try { localStorage.setItem("ares.glow", g ? "on" : "off"); } catch { /* */ } };
  const toast = useToast();
  useEffect(() => { getJSON("/api/anatomy/regions").then((r) => setMeta(r.regions)).catch(() => {}); }, []);
  useEffect(() => { if (s && (!aid || !s.crew.some((c: any) => c.id === aid))) setAid(s.selected); }, [s, aid]);

  // automated-action feedback: announce new incidents and simulation changes as they happen
  const seen = useRef<{ inc: Set<number>; sim: string | null; init: boolean }>({ inc: new Set(), sim: null, init: false });
  useEffect(() => {
    if (!s) return;
    const st = seen.current;
    for (const i of s.incidents) {
      if (!st.inc.has(i.id)) {
        st.inc.add(i.id);
        if (st.init) toast(`ARES opened health event #${i.id}: ${(i.event || "").replace("EVENT: ", "").toLowerCase()} (L${i.level}) — logged and queued for Earth`, "auto");
      }
    }
    const simKey = `${s.simulation?.state}:${s.simulation?.scenario}`;
    if (st.init && st.sim !== simKey && s.simulation?.state) toast(`Simulation: ${s.simulation.state}${s.simulation.title ? ` · ${s.simulation.title}` : ""}`, "auto");
    st.sim = simKey; st.init = true;
  }, [s]);

  const ctx = useMemo(() => ({ s, aid, setAid, go, reload, meta, glow, setGlow }), [s, aid, meta, glow]);
  const open = s ? s.incidents.filter((i: any) => i.closed === null && i.level >= 1).length : 0;
  const m = s?.mission;
  const Page = { overview: Overview, crew: Crew, body: BodyPage, insights: Insights, emergency: Emergency, alertness: Alertness, tests: TestHistory, sim: Simulation, system: System }[page] ?? Overview;
  const met = s ? Math.max(0, s.demo_minute) : 0;
  return (
    <AppCtx.Provider value={ctx}>
      {/* Animated glass backdrop. Off on the hologram page (it has its own 3D scene) and when "Glow" is off for slower computers. */}
      {glow && page !== "body" && (
        <div className="ares-bg" aria-hidden="true">
          <GlassFold color1="#1e3cc8" color2="#040914" color3="#7fdcff" speed={0.22} scale={0.85} noise={0.1} />
        </div>
      )}
      <div className="ares-scrim" aria-hidden="true" />
      <div className="shell">
        <header className="topbar">
          <div className="brand"><div className="brand-mark"><i /></div><div><b>ARES</b><small>ASTRONAUT HEALTH COMMAND</small></div></div>
          <div className="strip">
            {m && <>
              <div className="kv"><b>{m.phase}</b><span>Mission phase</span></div>
              <div className="kv"><b>Day {fmt(m.mission_day, 1)}</b><span>Mission day</span></div>
              <div className="kv"><b>T+{String(Math.floor(met / 60)).padStart(2, "0")}:{String(Math.floor(met % 60)).padStart(2, "0")}</b><span>Monitoring time</span></div>
              <div className="kv"><b>{fmt(m.one_way_light_time_min, 1)} min</b><span>Signal delay to Earth</span></div>
              <div className="kv"><b><span className={`link-state link-${m.comm_mode}`}>{m.comm_mode.toUpperCase()}</span></b><span>Earth link</span></div>
              <div className="kv"><b>{s.runtime.paused ? "PAUSED" : `${s.runtime.speed}×`}</b><span>Clock speed (min/s)</span></div>
            </>}
          </div>
          <div className="top-right">
            {s?.simulation?.state && s.simulation.state !== "idle" &&
              <button className={`sim-state sim-${s.simulation.state}`} onClick={() => go("sim")} title="Open Mission Simulation">
                SIM {s.simulation.state}{s.simulation.progress != null ? ` · ${Math.round(s.simulation.progress * 100)}%` : ""}</button>}
            <span className="tag sim" title="All crew physiology in this demo is simulated">Simulated crew data</span>
            {s && <select value={aid ?? ""} onChange={(e) => setAid(e.target.value)} aria-label="Select astronaut">
              {s.crew.map((c: any) => <option key={c.id} value={c.id}>{c.name} — {c.role}</option>)}</select>}
          </div>
        </header>
        <nav className="sidebar" aria-label="Main">
          {PAGES.map((p) => (
            <button key={p.id} className={`nav ${page === p.id ? "on" : ""}`} onClick={() => go(p.id)}>
              <Icon name={p.icon} />{p.label}{p.id === "emergency" && open > 0 && <span className="count">{open}</span>}
            </button>))}
          <div className="side-foot">
            Runs fully offline on this computer.<br />Decision support only — ARES does not diagnose or prescribe.<br />
            <a href="/classic">Classic dashboard</a>
          </div>
        </nav>
        <main className="main">
          {error && <div className="banner">Connection to the local ARES service lost — retrying every second. ({error})</div>}
          {!s ? <div className="loading">Connecting to the onboard ARES service…</div> : <Page />}
        </main>
      </div>
    </AppCtx.Provider>
  );
}
