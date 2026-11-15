import { useEffect, useRef, useState } from "react";
import { useApp } from "../App";
import { fmt, postJSON, usePoll } from "../api";
import { DataTag, Panel, Plot, PLOT_LAYOUT, Status, useToast } from "../ui";

/* ------------------------------------------------------------------ permanent saving (local database)
   A test record is opened when the test starts; every trial is sent as it happens (a crash keeps them);
   the final status (completed / stopped / terminated) and results are saved when it ends. "Saved" is shown
   only after the backend confirms the database write. Anything not yet confirmed is retried automatically. */
type Outcome = "response" | "lapse" | "false_start" | "miss" | "premature";
interface Pending { testId: string | null; aid: string; config: any; status: string; duration_s: number; trials: any[]; at: number }
const PENDING_KEY = "ares.pendingTests";
const loadPending = (): Pending[] => { try { return JSON.parse(localStorage.getItem(PENDING_KEY) || "[]"); } catch { return []; } };
const savePending = (p: Pending[]) => { try { localStorage.setItem(PENDING_KEY, JSON.stringify(p)); } catch { /* storage off */ } };
export const STATUS_S: Record<string, string> = { completed: "good", stopped: "watch", terminated: "elevated", interrupted: "elevated", legacy: "unknown", in_progress: "stable" };
export const STATUS_TEXT: Record<string, string> = { completed: "Completed", stopped: "Stopped early", terminated: "Terminated", interrupted: "Interrupted", legacy: "Saved by v0.4", in_progress: "In progress" };
async function deliver(p: Pending): Promise<any> {
  let tid = p.testId;
  if (!tid) tid = (await postJSON("/api/tests/sessions", { astronaut_id: p.aid, config: p.config })).test_id;
  return postJSON(`/api/tests/sessions/${tid}/finish`, { status: p.status, duration_s: p.duration_s, trials: p.trials });
}

type Phase = "ready" | "countdown" | "running" | "paused" | "completed" | "terminated" | "scoring";
const LAPSE = 355, FALSE_START = 130, MISS = 10000;

interface Trial { rt: number | null; kind: "ok" | "lapse" | "miss" | "fs" }

function stats(trials: Trial[], premature: number) {
  const v = trials.filter((t) => t.rt !== null && t.rt >= FALSE_START).map((t) => t.rt as number);
  const misses = trials.filter((t) => t.kind === "miss").length;
  if (!v.length) return { n: 0, misses, premature: premature + trials.filter((t) => t.kind === "fs").length, lapses: misses } as any;
  const sorted = [...v].sort((a, b) => a - b);
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  const sd = v.length > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (v.length - 1)) : 0;
  return { n: v.length, mean, median: sorted[Math.floor((sorted.length - 1) / 2)] / 2 + sorted[Math.ceil((sorted.length - 1) / 2)] / 2, fastest: sorted[0], slowest: sorted[sorted.length - 1], sd,
    misses, premature: premature + trials.filter((t) => t.kind === "fs").length, lapses: v.filter((x) => x >= LAPSE).length + misses, trials: trials.length };
}

function interpret(cur: any, prev: any[]): { text: string; s: string }[] {
  const out: { text: string; s: string }[] = [];
  const base = prev.filter((r) => r.valid).slice(0, 5);
  if (!base.length) return [{ text: "This is the first scored test for this astronaut in this session — it becomes the comparison point for the next ones.", s: "stable" }];
  const m = base.reduce((a, r) => a + r.stats.mean_rt_ms, 0) / base.length;
  const sd = base.reduce((a, r) => a + (r.stats.sd_ms ?? 0), 0) / base.length;
  const lp = base.reduce((a, r) => a + r.stats.lapses, 0) / base.length;
  const d = (cur.mean - m) / m;
  if (d <= -0.08) out.push({ text: `Faster than this astronaut's recent tests (${fmt(cur.mean, 0)} vs ${fmt(m, 0)} ms average) — improving.`, s: "good" });
  else if (d >= 0.1 || cur.lapses >= lp + 3) out.push({ text: `Slower than recent tests (${fmt(cur.mean, 0)} vs ${fmt(m, 0)} ms; lapses ${cur.lapses} vs ${fmt(lp, 1)}) — declining. Check sleep and workload; repeat the test.`, s: "watch" });
  else out.push({ text: `Consistent with this astronaut's recent tests (${fmt(cur.mean, 0)} vs ${fmt(m, 0)} ms).`, s: "stable" });
  if (sd > 0 && cur.sd > sd * 1.3) out.push({ text: `Reaction times are more variable than usual (spread ${fmt(cur.sd, 0)} vs ${fmt(sd, 0)} ms).`, s: "watch" });
  return out;
}

export default function Alertness() {
  const { s, aid } = useApp();
  const toast = useToast();
  const { data: hist, reload } = usePoll<any>(aid ? `/api/pvt/${aid}` : null, 5000);
  const [phase, setPhase] = useState<Phase>("ready");
  const [duration, setDuration] = useState(180);
  const [maxTrials, setMaxTrials] = useState(0);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [prem, setPrem] = useState(0);
  const [left, setLeft] = useState(0);
  const [result, setResult] = useState<any>(null);
  const stage = useRef<HTMLDivElement>(null);
  const big = useRef<HTMLDivElement>(null);
  const S = useRef<any>({ active: false, timers: [], raf: 0, shownAt: null, remaining: 0, segStart: 0, trials: [] as Trial[], prem: 0 });
  const [save, setSave] = useState<{ state: "idle" | "recording" | "saving" | "saved" | "error"; text?: string; testId?: string; status?: string }>({ state: "idle" });
  const [pendingN, setPendingN] = useState(loadPending().length);
  const config = () => ({ planned_duration_s: duration, max_trials: maxTrials || null, practice: duration === 60, ui: "React PVT-B" });
  // trial log sent to the backend as the test runs (incremental saving)
  const record = (outcome: Outcome, rt: number | null, isi: number | null) => {
    const x = S.current;
    x.seq = (x.seq || 0) + 1;
    x.buf.push({ trial_no: x.seq, outcome, rt_ms: rt === null ? null : Math.round(rt * 10) / 10, isi_ms: isi === null ? null : Math.round(isi),
      t_offset_ms: Math.max(0, Math.round(x.elapsedBase + (performance.now() - x.segStart))) });
    flush();
  };
  const flush = async () => {
    const x = S.current;
    if (!x.testId || x.flushing || !x.buf.length) return;
    x.flushing = true;
    const batch = x.buf.slice(0, 100);
    try {
      await postJSON(`/api/tests/sessions/${x.testId}/trials`, { trials: batch });
      const sent = new Set(batch.map((b: any) => b.trial_no));
      x.buf = x.buf.filter((b: any) => !sent.has(b.trial_no));
    } catch { /* kept in the buffer, sent with the next trial or at the end */ }
    x.flushing = false;
    if (x.buf.length && x.active) setTimeout(flush, 1500);
  };
  const elapsedS = () => { const x = S.current; const planned = x.config?.planned_duration_s ?? duration; return Math.round((planned * 1000 - Math.max(0, x.remaining - (x.paused ? 0 : performance.now() - x.segStart))) / 1000); };
  const persist = async (status: "completed" | "stopped" | "terminated") => {
    const x = S.current;
    const p: Pending = { testId: x.testId ?? null, aid: x.aid, config: x.config, status, duration_s: Math.max(0, elapsedS()), trials: x.buf, at: Date.now() };
    x.buf = [];
    setSave({ state: "saving", text: "Saving to the local database…" });
    try {
      const r = await deliver(p);
      if (!r?.persisted?.verified) throw new Error("the database did not confirm the write");
      setSave({ state: "saved", testId: r.persisted.test_id, status: r.persisted.status,
        text: `Saved to the local database — ${STATUS_TEXT[r.persisted.status] ?? r.persisted.status}, ${r.persisted.trials_saved} trials, test ${r.persisted.test_id}` });
      toast(`Test saved permanently (${STATUS_TEXT[r.persisted.status] ?? r.persisted.status}, ${r.persisted.trials_saved} trials)`, "ok");
      return r;
    } catch (e) {
      const q = loadPending(); q.push(p); savePending(q); setPendingN(q.length);
      setSave({ state: "error", text: `NOT saved yet (${(e as Error).message}). Kept on this computer and retried automatically.` });
      toast(`Test result not saved yet: ${(e as Error).message} — will retry automatically`, "err");
      return null;
    }
  };
  useEffect(() => {   // retry anything that could not be confirmed earlier (e.g. the service was restarting)
    const retry = async () => {
      const q = loadPending(); if (!q.length) return;
      const left: Pending[] = [];
      for (const p of q) { try { const r = await deliver(p); if (!r?.persisted?.verified) left.push(p); } catch { left.push(p); } }
      savePending(left); setPendingN(left.length);
      if (left.length < q.length) { toast(`${q.length - left.length} earlier test result(s) saved to the local database`, "ok"); reload(); }
    };
    retry(); const i = setInterval(retry, 10000); return () => clearInterval(i);
  }, []);

  const clearAll = () => {
    const x = S.current; x.timers.forEach((t: any) => clearTimeout(t)); x.timers = []; cancelAnimationFrame(x.raf); x.shownAt = null;
    stage.current?.classList.remove("go", "premature");
  };
  const show = (txt: string) => { if (big.current) big.current.textContent = txt; };
  const elapsedOk = () => { const x = S.current; return x.remaining - (performance.now() - x.segStart) > 0; };
  const schedule = () => {
    const x = S.current;
    if (!x.active) return;
    if (!elapsedOk() || (maxTrials && x.trials.length >= maxTrials)) { finish(false); return; }
    show("");
    const isi = 2000 + Math.random() * 3000;   // PVT-B inter-stimulus interval 2-5 s
    x.isi = isi;
    x.timers.push(setTimeout(() => {
      if (!x.active) return;
      stage.current?.classList.add("go");
      x.raf = requestAnimationFrame(() => {               // timestamp at the frame that paints the stimulus
        x.shownAt = performance.now();
        const loop = () => { if (x.shownAt !== null) { show(String(Math.round(performance.now() - x.shownAt))); x.raf = requestAnimationFrame(loop); } };
        x.raf = requestAnimationFrame(loop);
      });
      x.timers.push(setTimeout(() => respond(null, true), MISS));
    }, isi));
  };
  const respond = (ts: number | null, timeout = false) => {
    const x = S.current;
    if (!x.active) return;
    if (x.shownAt === null) {           // pressed with no stimulus = premature
      if (timeout) return;
      x.prem += 1; setPrem(x.prem); record("premature", null, null);
      stage.current?.classList.add("premature"); show("Too early");
      x.timers.forEach((t: any) => clearTimeout(t)); x.timers = [];
      x.timers.push(setTimeout(() => { stage.current?.classList.remove("premature"); schedule(); }, 700));
      return;
    }
    const now = performance.now();
    const rt = timeout ? null : Math.max(0, (ts && ts > 0 && Math.abs(ts - now) < 1000 ? ts : now) - x.shownAt);
    cancelAnimationFrame(x.raf); x.timers.forEach((t: any) => clearTimeout(t)); x.timers = []; x.shownAt = null;
    stage.current?.classList.remove("go");
    const kind: Trial["kind"] = rt === null ? "miss" : rt < FALSE_START ? "fs" : rt >= LAPSE ? "lapse" : "ok";
    x.trials = [...x.trials, { rt, kind }]; setTrials(x.trials);
    record(kind === "ok" ? "response" : kind === "fs" ? "false_start" : kind, rt, x.isi ?? null);
    show(rt === null ? "Missed" : `${Math.round(rt)} ms`);
    x.timers.push(setTimeout(schedule, 500));
  };
  const finish = async (early: boolean) => {
    const x = S.current; if (!x.active) return;
    const dur = elapsedS();
    x.active = false; clearAll(); setPhase("scoring"); show(early ? "Stopped" : "Done");
    const st = stats(x.trials, x.prem);
    x.remaining = Math.max(0, duration * 1000 - dur * 1000); x.paused = true;
    const r = await persist(early ? "stopped" : "completed");
    setResult({ local: st, server: r?.test ?? null });
    setPhase("completed"); reload();
  };
  const latest = useRef<{ respond: typeof respond }>({ respond });
  latest.current.respond = respond;
  useEffect(() => {   // window closed / app quit / page left mid-test -> saved as terminated (beacon survives the unload)
    const beacon = () => {
      const x = S.current;
      if (!(x.active || x.paused) || !x.testId || x.closed) return;
      x.closed = true;
      const body = JSON.stringify({ status: "terminated", duration_s: Math.max(0, elapsedS()), trials: x.buf });
      try { navigator.sendBeacon(`/api/tests/sessions/${x.testId}/beacon`, new Blob([body], { type: "text/plain" })); } catch { /* next start marks it interrupted */ }
    };
    window.addEventListener("pagehide", beacon);
    return () => { window.removeEventListener("pagehide", beacon); beacon(); };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      if (e.code === "Space" && S.current.active && !S.current.paused && !/INPUT|SELECT|TEXTAREA/.test(tgt?.tagName ?? "")) {
        e.preventDefault(); latest.current.respond(e.timeStamp);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); S.current.active = false; clearAll(); };   // stop timers on leave
  }, []);
  useEffect(() => {   // countdown of remaining time (display only)
    if (phase !== "running") return;
    const i = setInterval(() => { const x = S.current; setLeft(Math.max(0, Math.ceil((x.remaining - (performance.now() - x.segStart)) / 1000))); }, 250);
    return () => clearInterval(i);
  }, [phase]);

  const start = () => {
    if (S.current.active) return;                     // never two sessions
    setTrials([]); setPrem(0); setResult(null);
    S.current = { active: false, timers: [], raf: 0, shownAt: null, remaining: duration * 1000, segStart: 0, trials: [], prem: 0, paused: false,
      testId: null, seq: 0, buf: [], elapsedBase: 0, aid, config: config(), closed: false };
    const me = S.current;
    setSave({ state: "recording", text: "Opening a test record in the local database…" });
    postJSON("/api/tests/sessions", { astronaut_id: aid, test_type: "pvt", config: me.config })
      .then((r) => { me.testId = r.test_id; setSave({ state: "recording", testId: r.test_id, text: `Recording test ${r.test_id} — each trial is saved as it happens` }); flush(); })
      .catch((e) => setSave({ state: "error", text: `Could not open a test record (${(e as Error).message}); results will be saved when the service answers.` }));
    setPhase("countdown"); stage.current?.focus();
    let n = 3; show(String(n));
    const tick = () => {
      n -= 1;
      if (n > 0) { show(String(n)); S.current.timers.push(setTimeout(tick, 1000)); return; }
      S.current.active = true; S.current.segStart = performance.now(); setPhase("running"); schedule();
    };
    S.current.timers.push(setTimeout(tick, 1000));
  };
  const pause = () => {
    const x = S.current; if (!x.active || x.paused) return;
    x.remaining -= performance.now() - x.segStart; x.elapsedBase += performance.now() - x.segStart; x.paused = true;
    clearAll(); show("Paused"); setPhase("paused");   // a stimulus on screen is discarded, not scored
  };
  const resume = () => {
    const x = S.current; if (!x.active || !x.paused) return;
    x.paused = false; x.segStart = performance.now(); setPhase("running"); stage.current?.focus(); schedule();
  };
  const terminate = () => {
    const x = S.current;
    const running = x.active && !x.closed;
    const dur = elapsedS();
    x.active = false; clearAll(); show("Test terminated"); setPhase("terminated");
    if (running) { x.closed = true; x.remaining = Math.max(0, duration * 1000 - dur * 1000); x.paused = true; persist("terminated").then(() => reload()); }
  };
  const restart = () => { terminate(); setTimeout(start, 50); };
  const reset = () => { terminate(); setPhase("ready"); setTrials([]); setPrem(0); setResult(null); show(""); };

  const live = stats(trials, prem);
  const SM = result?.server?.result?.metrics;
  const R = SM ? { n: SM.responses, mean: SM.mean_rt_ms, median: SM.median_rt_ms, fastest: SM.fastest_ms, slowest: SM.slowest_ms, sd: SM.sd_ms,
    lapses: SM.lapses, misses: SM.misses, premature: SM.premature, trials: SM.trials, source: "saved" } : result?.local;
  const runs = hist?.runs ?? [];
  const download = () => {
    if (!R) return;
    const p = s.crew.find((c: any) => c.id === aid);
    const lines = [`ARES reaction time and alertness test (PVT-B protocol)`, `Astronaut: ${p?.name} (${aid})`, `Mission day: ${result.server?.run?.mission_day ?? "—"}`,
      `Duration setting: ${duration} s${maxTrials ? `, max ${maxTrials} trials` : ""}`, ``,
      `Average: ${fmt(R.mean, 0)} ms`, `Median: ${fmt(R.median, 0)} ms`, `Fastest: ${fmt(R.fastest, 0)} ms`, `Slowest: ${fmt(R.slowest, 0)} ms`, `Variability (SD): ${fmt(R.sd, 0)} ms`,
      `Lapses (>= ${LAPSE} ms or missed): ${R.lapses}`, `Missed (no response in 10 s): ${R.misses}`, `Premature (no stimulus or < ${FALSE_START} ms): ${R.premature}`, `Trials: ${R.trials}`,
      `Scored as PVT-B: ${result.server?.ok ? "yes" : "no (" + (result.server?.result?.reason ?? "not saved") + ")"}`, ``, `trial,reaction_time_ms,classification`,
      ...trials.map((t, i) => `${i + 1},${t.rt === null ? "" : t.rt.toFixed(1)},${t.kind}`), ``, `Not a diagnosis. Compare with the astronaut's own previous tests.`];
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain" }));
    a.download = `ARES_PVT_${aid}_${Date.now()}.txt`; a.click(); URL.revokeObjectURL(a.href);
  };
  const cl = s.detail.clinical;
  const [sym, setSym] = useState<Set<string>>(new Set());
  const [ci, setCi] = useState({ samn_perelli: 2, mood: 7, stress: 3, workload: 5, sleep_quality: 7 });
  const bv = s.detail.behavioral;
  return (
    <>
      <div className="page-head"><div><h1>Reaction Time and Alertness Test</h1>
        <p>The 3-minute PVT-B used on the International Space Station. Press <b>Space</b> or click the panel as soon as the counter appears. Results are compared with this astronaut's own earlier tests — one test is never a diagnosis.</p></div>
        <Status s={bv.assessment.level ? "observation" : "good"} text={`Alertness: ${bv.assessment.label}`} /></div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.35fr) minmax(0,1fr)" }}>
        <Panel title="Test" info="pvt" right={<Status s={phase === "running" ? "good" : phase === "paused" ? "watch" : phase === "terminated" ? "elevated" : "stable"} text={phase} />}>
          <div className="row" style={{ marginBottom: 10 }}>
            <label className="field">Duration<select value={duration} disabled={phase !== "ready" && phase !== "completed" && phase !== "terminated"} onChange={(e) => setDuration(+e.target.value)}>
              <option value={180}>3 min (standard PVT-B)</option><option value={90}>90 s (demo)</option><option value={60}>60 s (practice, not scored)</option></select></label>
            <label className="field">Trial limit<select value={maxTrials} disabled={phase !== "ready" && phase !== "completed" && phase !== "terminated"} onChange={(e) => setMaxTrials(+e.target.value)}>
              <option value={0}>No limit (time-based)</option><option value={20}>20 trials</option><option value={40}>40 trials</option></select></label>
            <span className="muted" style={{ fontSize: 12, alignSelf: "flex-end" }}>Testing: <b>{s.crew.find((c: any) => c.id === aid)?.name}</b></span>
          </div>
          <div ref={stage} className="pvt-stage" tabIndex={0} onPointerDown={(e) => { if (phase === "running") { e.preventDefault(); respond(e.timeStamp); } }}>
            <div>
              <div ref={big} className="big" />
              {phase === "ready" && <div className="prompt">Look at this panel. After <b>Start</b> and a 3-second countdown, a counter appears at random every 2–5 s. Press <b>Space</b> (or click here) as fast as you can. Don't press before it appears.</div>}
              {phase === "terminated" && <div className="prompt">Test terminated. The trials recorded so far are kept in the test history with the status <b>Terminated</b> (not scored).</div>}
              {phase === "scoring" && <div className="prompt">Scoring…</div>}
            </div>
          </div>
          <div className="row mt">
            <button className="btn primary" disabled={!(phase === "ready" || phase === "completed" || phase === "terminated")} onClick={start}>Start test</button>
            <button className="btn" disabled={phase !== "running"} onClick={pause}>Pause</button>
            <button className="btn" disabled={phase !== "paused"} onClick={resume}>Resume</button>
            <button className="btn warn" disabled={!(phase === "running" || phase === "paused")} onClick={() => finish(true)} title="End now and score the responses so far">Stop &amp; score</button>
            <button className="btn danger" disabled={!(phase === "running" || phase === "paused" || phase === "countdown")} onClick={terminate} title="Abort now: kept in the history as Terminated, not scored">Terminate</button>
            <button className="btn" disabled={phase === "scoring"} onClick={restart}>Restart</button>
            <button className="btn ghost" onClick={reset}>Reset</button>
          </div>
          {save.state !== "idle" && <div className={`save-line ${save.state}`} role="status">
            <span className="dot" />{save.text}
            {save.state === "saved" && save.testId && <a className="btn sm ghost" href={`#/tests?id=${save.testId}`}>Open in Test History</a>}</div>}
          {pendingN > 0 && <div className="note warn">{pendingN} test result(s) waiting to be saved — ARES retries every 10 s.</div>}
          {(phase === "running" || phase === "paused") && <div className="mt">
            <div className="progress"><i style={{ width: `${100 - (100 * left) / duration}%` }} /></div>
            <div className="row muted" style={{ fontSize: 12, marginTop: 4 }}><span>{left} s left</span><span>· {trials.length} trials</span><span>· {live.premature} premature</span><span>· {live.lapses} lapses</span>
              {live.n > 0 && <span>· running average {fmt(live.mean, 0)} ms</span>}</div></div>}
          {trials.length > 0 && <div className="mt"><div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Each response (ms)</div>
            <div className="rt-list">{trials.map((t, i) => <span key={i} className={t.kind === "ok" ? "" : t.kind}>{i + 1}: {t.rt === null ? "miss" : Math.round(t.rt)}</span>)}</div></div>}
        </Panel>
        <Panel title="Results" right={R && (save.state === "saved" && save.testId
          ? <span className="row"><a className="btn sm cyan" href={`/api/tests/${save.testId}/export.pdf`} download>PDF ↓</a><a className="btn sm" href={`/api/tests/${save.testId}/export.csv`} download>CSV ↓</a></span>
          : <button className="btn sm cyan" onClick={download}>Download (not saved) ↓</button>)}>
          {R && R.n ? <>
            <div className="stat-grid">
              <div className="stat"><b>{fmt(R.mean, 0)}</b><span>Average (ms)</span></div><div className="stat"><b>{fmt(R.median, 0)}</b><span>Median (ms)</span></div>
              <div className="stat"><b>{fmt(R.fastest, 0)}</b><span>Fastest (ms)</span></div><div className="stat"><b>{fmt(R.slowest, 0)}</b><span>Slowest (ms)</span></div>
              <div className="stat"><b>{R.lapses}</b><span>Lapses (≥{LAPSE} ms or missed)</span></div><div className="stat"><b>{R.misses}</b><span>Missed (10 s)</span></div>
              <div className="stat"><b>{R.premature}</b><span>Premature</span></div><div className="stat"><b>{fmt(R.sd, 0)}</b><span>Variability (SD, ms)</span></div>
              <div className="stat"><b>{R.trials}</b><span>Trials completed</span></div>
            </div>
            <Plot className="plot xs" data={[{ type: "histogram", x: trials.filter((t) => t.rt !== null).map((t) => t.rt), xbins: { size: 25 }, marker: { color: "#3fd8ff" }, hovertemplate: "%{x} ms: %{y}<extra></extra>" }]}
              layout={PLOT_LAYOUT({ margin: { l: 28, r: 6, t: 4, b: 26 }, hovermode: "closest", shapes: [{ type: "line", x0: LAPSE, x1: LAPSE, y0: 0, y1: 1, yref: "paper", line: { color: "#f2c94c", dash: "dot" } }],
                xaxis: { gridcolor: "rgba(110,170,255,.08)", title: { text: "reaction time (ms) — dotted line = lapse threshold", font: { size: 10 } } } })} />
            <h4>What this means</h4>
            {(result?.server?.result?.interpretation ?? interpret(R, runs.slice(1))).map((x: any, i: number) => <div key={i} className="row" style={{ marginBottom: 4 }}>
              <Status s={x.s} text={x.kind === "status" ? "Status" : x.kind === "note" ? "Note" : x.kind === "data" ? "Data" : x.s === "good" ? "Faster" : x.s === "watch" ? "Attention" : "Consistent"} /><span className="ink2">{x.text}</span></div>)}
            {result?.server && !result.server.result?.scored && <div className="note warn">Not scored as a PVT-B ({result.server.status === "completed" ? result.server.result?.score?.reason ?? "too few responses" : `test ${STATUS_TEXT[result.server.status]?.toLowerCase()}`}). Kept in the history but not used for the personal baseline or the alertness assessment.</div>}
            {!result?.server && <div className="note warn">This result is not saved yet (see the status line).</div>}
            <div className="kv1"><span>Sleep in the last 24 h</span><b className="num">{fmt(hist?.sleep_h_24h, 1)} h</b></div>
            <div className="kv1"><span>Latest fatigue rating (1–7)</span><b className="num">{bv.series.samn_perelli?.slice(-1)[0] ?? "—"}</b></div>
            <p className="muted" style={{ fontSize: 12 }}>Lapse = response ≥ {LAPSE} ms or no response within 10 s; premature = press with no stimulus or faster than {FALSE_START} ms (Basner et al. 2011, PVT-B).</p>
          </> : <div className="empty">{phase === "completed" ? "No valid responses recorded." : "Results appear here when a test ends."}</div>}
        </Panel>
      </div>
      <div className="grid g2 mt">
        <Panel title="Previous tests (saved permanently)" info="pvthistory" right={<span className="row"><DataTag kind="meas" /><a className="btn sm ghost" href="#/tests">All tests →</a></span>}>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Date</th><th className="r">Mission day</th><th className="r">Average</th><th className="r">Median</th><th className="r">Lapses</th><th className="r">Premature</th><th className="r">Variability</th><th>Status</th><th>Scored</th><th /></tr></thead>
            <tbody>{runs.length ? runs.slice(0, 15).map((r: any) => (
              <tr key={r.id}><td>{r.started_at ? new Date(r.started_at * 1000).toLocaleString() : "—"}</td><td className="r">{fmt(r.mission_day, 2)}</td>
                <td className="r">{r.stats?.mean_rt_ms == null ? "—" : `${fmt(r.stats.mean_rt_ms, 0)} ms`}</td><td className="r">{r.stats?.median_rt_ms == null ? "—" : `${fmt(r.stats.median_rt_ms, 0)} ms`}</td>
                <td className="r">{r.stats?.lapses ?? "—"}</td><td className="r">{r.stats?.premature ?? "—"}</td><td className="r">{r.stats?.sd_ms == null ? "—" : `${fmt(r.stats.sd_ms, 0)} ms`}</td>
                <td>{r.status ? <Status s={STATUS_S[r.status] ?? "unknown"} text={STATUS_TEXT[r.status] ?? r.status} /> : "—"}</td>
                <td>{r.valid ? <Status s="good" text="yes" /> : <Status s="unknown" text="no" />}</td>
                <td>{r.test_id && <a className="btn sm ghost" href={`#/tests?id=${r.test_id}`}>Details</a>}</td></tr>))
              : <tr><td colSpan={10} className="muted">No saved reaction tests for this astronaut yet.</td></tr>}</tbody>
          </table></div>
        </Panel>
        <Panel title="Alertness over the mission" right={<DataTag kind="sim" />}>
          <Plot className="plot sm" data={[{ x: bv.series.pvt_day, y: bv.series.speed, mode: "lines+markers", line: { color: "#3fd8ff", width: 2 }, marker: { size: 6 }, hovertemplate: "day %{x:.1f}: speed %{y:.2f}/s<extra></extra>" }]}
            layout={PLOT_LAYOUT({ hovermode: "closest", yaxis: { gridcolor: "rgba(110,170,255,.08)", title: { text: "response speed (1/s, higher = more alert)", font: { size: 10 } } }, xaxis: { gridcolor: "rgba(110,170,255,.08)", title: { text: "mission day", font: { size: 10 } } } })} />
          <div className="muted" style={{ fontSize: 12 }}>{bv.assessment.note}</div>
        </Panel>
      </div>
      <div className="grid g2 mt">
        <Panel title="Daily check-in" right={<span className="tag">private: astronaut + medical officer</span>}>
          <div className="grid g2">{([["samn_perelli", "Fatigue (1 fully alert – 7 exhausted)", 1, 7], ["mood", "Mood (0–10)", 0, 10], ["stress", "Stress (0–10)", 0, 10], ["workload", "Workload (0–10)", 0, 10], ["sleep_quality", "Sleep quality (0–10)", 0, 10]] as const).map(([k, lab, a, b]) => (
            <label key={k} className="field">{lab}: <b>{(ci as any)[k]}</b><input type="range" min={a} max={b} value={(ci as any)[k]} onChange={(e) => setCi({ ...ci, [k]: +e.target.value })} /></label>))}</div>
          <button className="btn primary mt" onClick={async () => { try { const r = await postJSON(`/api/behavioral/${aid}/checkin`, ci); r.persisted?.verified ? toast("Check-in saved permanently to the local database", "ok") : toast(`Check-in used by ARES but NOT saved: ${r.persisted?.error ?? "no confirmation"}`, "err"); } catch (e) { toast(String(e), "err"); } }}>Save check-in</button>
        </Panel>
        <Panel title="Symptoms" right={<span className="tag">private</span>}>
          <div className="chips">{cl.symptom_options.map((o: string) => <button key={o} className={`chip ${sym.has(o) ? "on" : ""}`} onClick={() => { const n = new Set(sym); n.has(o) ? n.delete(o) : n.add(o); setSym(n); }}>{o.replace(/_/g, " ")}</button>)}</div>
          <button className="btn mt" disabled={!sym.size} onClick={async () => { try { const r = await postJSON(`/api/clinical/${aid}/symptoms`, { symptoms: [...sym] }); setSym(new Set()); r.persisted?.verified ? toast("Symptom report saved permanently", "ok") : toast(`Symptoms used by ARES but NOT saved: ${r.persisted?.error ?? "no confirmation"}`, "err"); } catch (e) { toast(String(e), "err"); } }}>Report selected symptoms</button>
          <div className="kv1 mt"><span>Reported in the last 24 h</span><b>{cl.active_symptoms_24h.join(", ").replace(/_/g, " ") || "none"}</b></div>
          {(cl.labs.flags || []).map((f: string, i: number) => <div key={i} className="note warn">{f}</div>)}
        </Panel>
      </div>
    </>
  );
}
