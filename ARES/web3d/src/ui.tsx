import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { STATE_COLOR, STATE_LABEL } from "./api";
import { INFO } from "./info";

declare const Plotly: any;

/* ------------------------------------------------------------------ toasts (visual feedback for every action) */
type Toast = { id: number; text: string; kind: "ok" | "err" | "auto" };
const ToastCtx = createContext<(text: string, kind?: Toast["kind"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = (text: string, kind: Toast["kind"] = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { id, text, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "err" ? 8000 : 4200);
  };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

/* ------------------------------------------------------------------ info button */
export function InfoButton({ k }: { k: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const ref = useRef<HTMLButtonElement>(null);
  const info = INFO[k];
  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  if (!info) return null;
  const toggle = () => {
    const r = ref.current!.getBoundingClientRect();
    const w = Math.min(460, window.innerWidth * 0.92);
    setPos({ x: Math.max(8, Math.min(r.left, window.innerWidth - w - 8)), y: Math.min(r.bottom + 6, window.innerHeight - 200) });
    setOpen((o) => !o);
  };
  return (
    <>
      <button ref={ref} className="info-btn" onClick={toggle} aria-label={`About: ${info.title}`} title={`What is "${info.title}"?`}>i</button>
      {open && (
        <div className="info-pop" style={{ left: pos.x, top: pos.y }} role="dialog" aria-label={info.title}>
          <button className="x" onClick={() => setOpen(false)} aria-label="close">×</button>
          <b style={{ fontSize: 14 }}>{info.title}</b>
          <h4>What it shows</h4><p>{info.what}</p>
          <h4>Why it matters</h4><p>{info.why}</p>
          {info.columns && <><h4>Columns</h4><dl>{info.columns.map(([a, b]) => [<dt key={a}>{a}</dt>, <dd key={a + "d"}>{b}</dd>])}</dl></>}
          {info.how && <><h4>How it is calculated</h4><p>{info.how}</p></>}
          {info.units && <><h4>Units</h4><p>{info.units}</p></>}
          {info.abnormal && <><h4>Reading unusual values</h4><p>{info.abnormal}</p></>}
          <h4>Where the data comes from</h4><p>{info.origin}</p>
          <p><span className="tag sim">{info.kind}</span></p>
        </div>
      )}
    </>
  );
}

export function Panel({ title, info, right, children, className = "" }: { title?: ReactNode; info?: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {(title || right) && <div className="panel-head"><h3>{title}</h3>{info && <InfoButton k={info} />}<span className="sp" />{right}</div>}
      {children}
    </section>
  );
}

export function Status({ s, text }: { s: string; text?: string }) {
  return <span className={`pill s-${s}`}><i />{text ?? STATE_LABEL[s] ?? s}</span>;
}
export function LevelPill({ level, text }: { level: number; text?: string }) {
  const s = ["normal", "observation", "elevated", "critical"][level] ?? "unknown";
  return <Status s={s} text={text ?? ["Normal", "Watch", "Medical check needed", "Emergency"][level]} />;
}
export function DataTag({ kind }: { kind: "sim" | "real" | "model" | "meas" }) {
  const t = { sim: "Simulated", real: "Real NASA data", model: "Model estimate", meas: "Measured" }[kind];
  return <span className={`tag ${kind}`}>{t}</span>;
}

/* ------------------------------------------------------------------ sparkline with personal band */
export function Spark({ values, lo, hi, w = 120, h = 30, color = STATE_COLOR.normal }:
  { values: (number | null)[]; lo?: number | null; hi?: number | null; w?: number; h?: number; color?: string }) {
  const vs = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (vs.length < 2) return <svg width={w} height={h} />;
  const all = [...vs, ...(lo != null ? [lo] : []), ...(hi != null ? [hi] : [])];
  const mn = Math.min(...all), mx = Math.max(...all), span = mx - mn || 1;
  const X = (i: number) => (i / (values.length - 1)) * (w - 4) + 2;
  const Y = (v: number) => h - 3 - ((v - mn) / span) * (h - 6);
  let d = ""; values.forEach((v, i) => { if (v === null) return; d += `${d ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; });
  const last = values.length - 1;
  return (
    <svg width={w} height={h} aria-label="trend">
      {lo != null && hi != null && <rect x={0} y={Y(hi)} width={w} height={Math.max(1, Y(lo) - Y(hi))} fill="rgba(63,216,255,.10)" />}
      <path d={d} fill="none" stroke={color} strokeWidth={1.8} />
      {values[last] != null && <circle cx={X(last)} cy={Y(values[last] as number)} r={2.6} fill={color} />}
    </svg>
  );
}

/* ------------------------------------------------------------------ Plotly (served locally, offline) */
export const PLOT_LAYOUT = (extra: any = {}) => ({
  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  font: { family: "Inter, Segoe UI, system-ui, sans-serif", size: 11, color: "#a7b9d4" },
  margin: { l: 42, r: 10, t: 6, b: 28 }, showlegend: false, hovermode: "x unified",
  xaxis: { gridcolor: "rgba(110,170,255,.10)", zeroline: false, linecolor: "rgba(110,170,255,.2)" },
  yaxis: { gridcolor: "rgba(110,170,255,.10)", zeroline: false, linecolor: "rgba(110,170,255,.2)" },
  hoverlabel: { bgcolor: "#0a1730", bordercolor: "#3fd8ff", font: { color: "#e6f0ff", size: 11 } }, ...extra,
});
export function Plot({ data, layout, className = "plot" }: { data: any[]; layout: any; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (ref.current && typeof Plotly !== "undefined") Plotly.react(ref.current, data, layout, { displayModeBar: false, responsive: true });
  }, [data, layout]);
  useEffect(() => () => { if (ref.current && typeof Plotly !== "undefined") Plotly.purge(ref.current); }, []);
  if (typeof Plotly === "undefined") return <div className={className + " empty"}>Chart library not loaded.</div>;
  return <div ref={ref} className={className} />;
}

/* ------------------------------------------------------------------ icons (inline, offline) */
const P: Record<string, string> = {
  overview: "M3 12l9-8 9 8M5 10v10h14V10",
  crew: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 4-6 8-6s8 2 8 6",
  body: "M12 2a2.5 2.5 0 110 5 2.5 2.5 0 010-5zM8 8h8l-1 7h-2l-.5 7h-1L11 15H9L8 8z",
  ai: "M4 17l5-6 4 3 7-9M4 21h16",
  emergency: "M12 3l10 18H2L12 3zm0 6v5m0 3v.5",
  alert: "M12 7v5l3 3M12 21a9 9 0 110-18 9 9 0 010 18z",
  sim: "M5 3l14 9-14 9V3z",
  tests: "M8 3h8v3H8zM6 5H4v16h16V5h-2M8 11h8M8 15h8M8 19h5",
  system: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12l2-1-1-3-2 .5-1.5-1.5.5-2-3-1-1 2h-2l-1-2-3 1 .5 2L6 8 4 7.5 3 10.5l2 1.5v0l-2 1.5 1 3 2-.5 1.5 1.5-.5 2 3 1 1-2h2l1 2 3-1-.5-2 1.5-1.5 2 .5 1-3z",
};
export function Icon({ name }: { name: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round"><path d={P[name]} /></svg>;
}
