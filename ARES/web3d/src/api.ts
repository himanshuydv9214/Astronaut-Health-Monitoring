/* Data access for the local ARES backend. Every number on screen comes from these endpoints. */
import { useCallback, useEffect, useRef, useState } from "react";

export type RegionState = "critical" | "elevated" | "observation" | "normal" | "unknown" | "not_monitored";

export async function getJSON<T = any>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 160)}`);
  return r.json();
}
export async function postJSON<T = any>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { const j = await r.json(); msg = j.detail || j.error || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}

/** Poll an endpoint; keeps the last good value; `reload` forces an immediate refresh. */
export function usePoll<T = any>(path: string | null, ms: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    const run = async () => {
      try { const d = await getJSON<T>(path); if (alive) { setData(d); setError(null); } }
      catch (e) { if (alive) setError(String((e as Error).message || e)); }
    };
    run();
    const id = setInterval(run, ms);
    return () => { alive = false; clearInterval(id); };
  }, [path, ms, tick]);
  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { data, error, reload };
}

/** Live anatomical state: WebSocket push with polling fallback. */
export function useAnatomy(astronaut: string | null) {
  const [data, setData] = useState<any>(null);
  const [live, setLive] = useState<"ws" | "poll" | "down">("down");
  const wsRef = useRef<WebSocket | null>(null);
  useEffect(() => {
    if (!astronaut) return;
    let alive = true;
    let poll: ReturnType<typeof setInterval> | null = null;
    const startPoll = () => {
      if (poll || !alive) return;
      const run = async () => {
        try { const d = await getJSON(`/api/anatomy?astronaut=${astronaut}`); if (alive) { setData(d); setLive("poll"); } }
        catch { if (alive) setLive("down"); }
      };
      run(); poll = setInterval(run, 1000);
    };
    try {
      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/anatomy?astronaut=${astronaut}`);
      wsRef.current = ws;
      ws.onmessage = (ev) => { if (alive) { setData(JSON.parse(ev.data)); setLive("ws"); } };
      ws.onerror = () => startPoll();
      ws.onclose = () => startPoll();
    } catch { startPoll(); }
    return () => { alive = false; if (poll) clearInterval(poll); wsRef.current?.close(); };
  }, [astronaut]);
  return { data, live };
}

/* ------------------------------------------------------------------ vocabulary (plain language first) */
export const LEVEL = ["Normal", "Watch", "Medical check needed", "Emergency"];
export const LEVEL_STATE: RegionState[] = ["normal", "observation", "elevated", "critical"];
export const STATE_COLOR: Record<string, string> = {
  normal: "#3fd8ff", observation: "#f2c94c", elevated: "#ff8a3d", critical: "#ff4d5e", unknown: "#8090a8", not_monitored: "#34435c",
};
export const STATE_LABEL: Record<string, string> = {
  normal: "Normal", observation: "Watch", elevated: "Medical check needed", critical: "Emergency",
  unknown: "Not enough data", not_monitored: "No sensor here",
};
export const VITALS: [string, string, string, number][] = [
  ["hr", "Heart rate", "bpm", 0], ["spo2", "Blood oxygen (SpO₂)", "%", 0], ["rr", "Breathing rate", "/min", 1],
  ["sbp", "Blood pressure", "mmHg", 0], ["temp", "Body temp (est.)", "°C", 2], ["hrv_rmssd", "Heart rate variability", "ms", 0],
];
export const CONTEXT: Record<string, string> = { rest: "Resting", sleep: "Sleeping", exercise: "Exercising", recovery: "Recovering after exercise", work: "Working" };

export const fmt = (v: any, d = 1) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d));
export const relT = (t: number, t0: number) => {
  const m = t - t0; const a = Math.abs(m);
  return `T${m < 0 ? "−" : "+"}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(Math.floor(a % 60)).padStart(2, "0")}`;
};
export const ago = (min: number | null | undefined) => {
  if (min === null || min === undefined) return "—";
  if (min < 1) return "just now";
  if (min < 60) return `${Math.round(min)} min ago`;
  return `${(min / 60).toFixed(1)} h ago`;
};
