/* ARES command interface. Polls the local API; renders with Plotly (served locally, offline). */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (x) => String(x ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d));
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const LVL = ["Normal", "Observation", "Medical assessment", "Critical"];
const badge = (l, txt) => `<span class="lvl l${l}">${esc(txt ?? `L${l} ${LVL[l]}`)}</span>`;
const VITALS = [
  ["hr", "Heart rate", "bpm", 0], ["spo2", "SpO₂", "%", 0], ["rr", "Resp. rate", "br/min", 1],
  ["sbp", "Systolic BP", "mmHg", 0], ["temp", "Core temp (est.)", "°C", 2], ["hrv_rmssd", "HRV RMSSD", "ms", 0],
];

const S = { tab: "overview", sel: null, data: null, inc: null, sym: new Set(), pvt: null, sys: null, busy: false };

/* ------------------------------------------------------------------ api */
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

/* ------------------------------------------------------------------ plot helpers */
function baseLayout(extra = {}) {
  const grid = "#2a2a28";
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: css("--sans"), size: 11, color: css("--text-2") },
    margin: { l: 44, r: 12, t: 8, b: 30 }, showlegend: false, hovermode: "x unified",
    xaxis: { gridcolor: grid, zeroline: false, linecolor: grid, tickfont: { size: 10 } },
    yaxis: { gridcolor: grid, zeroline: false, linecolor: grid, tickfont: { size: 10 } },
    hoverlabel: { bgcolor: "#222220", bordercolor: "#3a3a36", font: { color: "#f0efec", size: 11 } },
  }, extra);
}
const CFG = { displayModeBar: false, responsive: true };
function plot(id, traces, layout) { const el = document.getElementById(id); if (el) Plotly.react(el, traces, layout, CFG); }

/* ------------------------------------------------------------------ header */
function renderHeader(d) {
  const m = d.mission;
  const met = d.demo_minute;
  const hh = Math.floor(Math.max(met, 0) / 60), mm = Math.floor(Math.max(met, 0) % 60);
  $("#missionStrip").innerHTML = [
    ["Mission phase", m.phase], ["Mission day", fmt(m.mission_day, 2)],
    ["Live monitoring", `T+${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`],
    ["Distance to Earth", `${fmt(m.distance_au, 3)} AU`], ["One-way light time", `${fmt(m.one_way_light_time_min, 1)} min`],
    ["Earth link", `<span class="mode ${m.comm_mode}">${m.comm_mode.toUpperCase()}</span>`],
    ["Days to Mars", fmt(m.days_to_mars, 0)],
    ["Sim speed", d.runtime.paused ? "PAUSED" : `${d.runtime.speed} min/s`],
  ].map(([k, v]) => `<div class="kv"><b>${v}</b><span>${k}</span></div>`).join("");
  const open = d.incidents.filter((i) => i.closed === null && i.level >= 1).length;
  $("#incBadge").textContent = open || "";
  $("#footer").textContent = d.disclaimer + "  ·  Edge tick " + d.runtime.tick_ms + " ms";
}

/* ------------------------------------------------------------------ overview */
function renderOverview(d) {
  $("#crewCards").innerHTML = d.crew.map((c) => {
    const vit = VITALS.map(([k, lab, u, dp]) => {
      const v = c.values[k], z = c.z[k];
      const cls = v === null ? "na" : Math.abs(z ?? 0) >= 3 ? "dev" : "";
      return `<div class="v ${cls}"><b>${fmt(v, dp)}</b><span>${lab}</span></div>`;
    }).join("");
    const beh = d.behavioral[c.id];
    return `<div class="panel card l${c.level} ${c.id === S.sel ? "sel" : ""}" data-aid="${c.id}">
      <div class="card-head"><div><div class="nm">${esc(c.name)}</div><div class="rl">${esc(c.role)} · ${esc(c.context)}</div></div>
      ${badge(c.level, `L${c.level} ${c.label}`)}</div>
      <div class="vgrid">${vit}</div>
      <div class="card-foot">
        <span class="pill ${c.sensor_health !== "OK" ? "warn" : ""}">Sensors ${c.sensor_health}</span>
        <span class="pill">Confidence ${c.confidence}</span>
        <span class="pill ${beh && beh.level ? "warn" : ""}">Behavioral ${beh ? beh.label : "—"}</span>
        <span class="pill">Risk ${c.risk === null ? "—" : fmt(c.risk, 2)}</span>
        ${c.post_event ? '<span class="pill warn">Post-event monitoring</span>' : ""}
      </div></div>`;
  }).join("");
  $$("#crewCards .card").forEach((el) => el.onclick = () => { setSel(el.dataset.aid); switchTab("twin"); });

  const open = d.incidents.filter((i) => i.closed === null);
  $("#ovIncidents").innerHTML = open.length ? open.map((i) => incLi(i, d)).join("") : '<p class="muted">No active incidents.</p>';
  $$("#ovIncidents .li").forEach((el) => el.onclick = () => { S.inc = +el.dataset.id; switchTab("emergency"); });

  const m = d.mission;
  const q = d.comms.filter((x) => x.status === "queued");
  $("#ovComms").innerHTML = `
    <div class="stat"><span>Link</span><b><span class="mode ${m.comm_mode}">${m.comm_mode.toUpperCase()}</span> ${esc(m.comm_reason || "")}</b></div>
    <div class="stat"><span>One-way delay</span><b>${fmt(m.one_way_light_time_min, 1)} min</b></div>
    <div class="stat"><span>Earliest ground reply</span><b>${m.comm_mode === "blackout" ? "none (blackout)" : fmt(m.round_trip_min + 5, 0) + " min"}</b></div>
    <div class="stat"><span>Queued messages</span><b>${d.comms_pending}</b></div>
    ${q.slice(0, 4).map((x) => `<div class="logline"><span class="t">P${x.priority}</span>${esc(x.summary)}</div>`).join("")}
    <p class="muted">ARES never assumes Earth can intervene: onboard analysis continues in every link state.</p>`;

  const cb = d.cabin || {};
  if (cb.current) {
    const pct = Math.min(100, 100 * cb.co2_1h / 6);
    $("#ovCabin").innerHTML = `
      <div class="stat"><span>ppCO₂ (1-h mean)</span><b>${fmt(cb.co2_1h, 2)} mmHg</b></div>
      <div class="bar"><i style="width:${pct}%;background:${cb.co2_1h > 3 ? css("--critical") : cb.co2_1h > 2.5 ? css("--warning") : css("--series-1")}"></i></div>
      <div class="muted">Limit 3.0 mmHg (NASA-STD-3001 V2 6004) · 7-day advisory 2.5 mmHg</div>
      <div class="stat"><span>7-day mean</span><b>${fmt(cb.co2_7d, 2)} mmHg</b></div>
      <div class="stat"><span>Temperature / humidity</span><b>${fmt(cb.current.temp_c, 1)} °C · ${fmt(cb.current.rh_pct, 0)} %</b></div>
      <div class="stat"><span>Status</span><b>${badge(cb.level, (cb.findings || []).length ? "Out of limits" : cb.attribution && cb.level ? "Crew-wide effect" : "Within limits")}</b></div>
      ${(cb.findings || []).map((f) => `<div class="logline l2">${esc(f)}</div>`).join("")}
      ${cb.attribution ? `<div class="ctxbox"><b>Attribution:</b> ${esc(cb.attribution.text)}</div>` : ""}`;
  }

  $("#ovRad").innerHTML = (d.spe_active ? `<div class="logline l2">SOLAR PARTICLE EVENT ACTIVE — crew ${d.shelter ? "in storm shelter" : "should shelter"}</div>` : "") +
    d.crew.map((c) => {
      const x = c.dose;
      return `<div class="stat"><span>${esc(c.name)}</span><b>${fmt(x.career_total_msv, 0)} / ${x.career_limit_msv} mSv</b></div>
      <div class="bar"><i style="width:${Math.min(100, x.pct_career_limit)}%"></i></div>`;
    }).join("") +
    `<p class="muted">Career limit NASA-STD-3001 (600 mSv). Mission dose: measured (simulated dosimeter) vs modelled (MSL/RAD rates).
     Individual cancer risk is <b>not computed</b>: short-term dosimetry cannot predict it.</p>
     ${d.donki ? `<p class="muted">NASA DONKI cache: ${d.donki.n} real SEP records (fetched ${esc(d.donki.fetched)}).</p>` : '<p class="muted">NASA DONKI SEP cache: empty (run scripts/fetch_data.py with network).</p>'}`;

  const th = [...Array(121).keys()].map((i) => i * Math.PI / 60);
  plot("trajPlot", [
    { x: th.map(Math.cos), y: th.map(Math.sin), mode: "lines", line: { color: "#3a3a36", width: 1 }, hoverinfo: "skip" },
    { x: th.map((t) => 1.524 * Math.cos(t)), y: th.map((t) => 1.524 * Math.sin(t)), mode: "lines", line: { color: "#3a3a36", width: 1, dash: "dot" }, hoverinfo: "skip" },
    { x: [0], y: [0], mode: "markers+text", marker: { size: 10, color: css("--warning") }, text: ["Sun"], textposition: "bottom center", hoverinfo: "skip" },
    (() => { const nM = 2 * Math.PI / 686.98, th = Math.PI - nM * m.transfer_days + nM * m.mission_day;
      return { x: [1.524 * Math.cos(th)], y: [1.524 * Math.sin(th)], mode: "markers+text", marker: { size: 9, color: css("--series-2") }, text: ["Mars"], textposition: "middle left", hovertemplate: "Mars<extra></extra>" }; })(),
    { x: [m.earth_xy_au[0]], y: [m.earth_xy_au[1]], mode: "markers+text", marker: { size: 9, color: css("--series-1") }, text: ["Earth"], textposition: "top center", hovertemplate: "Earth<extra></extra>" },
    { x: [m.sc_xy_au[0]], y: [m.sc_xy_au[1]], mode: "markers+text", marker: { size: 9, color: css("--text"), symbol: "diamond" }, text: ["ARES crew"], textposition: "top center", hovertemplate: "Spacecraft<extra></extra>" },
    { x: [m.earth_xy_au[0], m.sc_xy_au[0]], y: [m.earth_xy_au[1], m.sc_xy_au[1]], mode: "lines", line: { color: css("--series-1"), width: 1, dash: "dash" }, hovertemplate: `${fmt(m.one_way_light_time_min, 1)} min light time<extra></extra>` },
  ], baseLayout({ margin: { l: 10, r: 10, t: 4, b: 4 }, hovermode: "closest",
    xaxis: { visible: false, range: [-1.8, 1.8], scaleanchor: "y" }, yaxis: { visible: false, range: [-1.7, 1.7] } }));

  $("#ovLog").innerHTML = d.log.slice(0, 40).map(logLine(d)).join("");
}
const tRel = (d, t) => { const m = t - (d.t - d.demo_minute); const s = m < 0 ? "-" : "+"; const a = Math.abs(m); return `T${s}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(Math.floor(a % 60)).padStart(2, "0")}`; };
const logLine = (d) => (l) => `<div class="logline l${l.level}"><span class="t">${tRel(d, l.t)}</span><span>${esc(l.text)}</span></div>`;
const who = (d, aid) => (d.crew.find((c) => c.id === aid) || {}).name || (aid === "ENV" ? "Radiation environment" : aid === "CABIN" ? "Cabin environment" : aid);
function incLi(i, d) {
  return `<div class="li l${i.level} ${i.id === S.inc ? "sel" : ""}" data-id="${i.id}"><span class="t">#${i.id} ${tRel(d, i.opened)}</span>
    ${badge(i.closed === null ? i.level : 0, i.closed === null ? `L${i.level}` : "resolved")} <b>${esc(who(d, i.astronaut_id))}</b>
    <div class="muted">${esc(i.event || "")} · peak L${i.peak_level}${i.acknowledged ? " · acknowledged" : ""}</div></div>`;
}

/* ------------------------------------------------------------------ twin */
function renderTwin(d) {
  const det = d.detail, p = det.profile, cls = det.classification;
  const c = d.crew.find((x) => x.id === p.id);
  $("#twinHead").innerHTML = `<div><div class="nm">${esc(p.name)}</div><div class="muted">${esc(p.role)} · age ${p.age} · fictional profile</div></div>
    ${badge(cls.level, `L${cls.level} ${cls.label}`)}
    <div class="kv"><b>${esc(c.context)}</b><span>Activity context</span></div>
    <div class="kv"><b>${esc(c.sensor_health)}</b><span>Sensor health</span></div>
    <div class="kv"><b>${esc(det.ecg ? det.ecg.hr_source : "—")}</b><span>HR source</span></div>
    <div class="kv"><b>${fmt(c.sleep_h_24h, 1)} h</b><span>Sleep (24 h, actigraphy)</span></div>
    <div class="kv"><b>${cls.confidence_label} (${cls.confidence})</b><span>Detection confidence</span></div>
    <div class="muted" style="flex-basis:100%">History: ${esc(p.history.join("; "))}. ${esc(p.notes || "")}</div>`;
  const r = det.recent, x = r.t.map((t) => (t - (d.t - d.demo_minute)) / 60);
  const el = $("#vitalPlots");
  if (!el.children.length) el.innerHTML = VITALS.map(([k, lab, u]) => `<div class="panel"><h3>${lab} <span class="hint">${u} · band = personal expected ±2σ</span></h3><div id="vp_${k}" class="plot xs"></div></div>`).join("");
  VITALS.forEach(([k, lab, u, dp]) => {
    const tr = [
      { x, y: r.hi[k], mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x, y: r.lo[k], mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: css("--band"), name: "personal band", hovertemplate: "band low %{y:.1f}<extra></extra>" },
      { x, y: r.e[k], mode: "lines", line: { color: "#8d8c84", width: 1, dash: "dot" }, name: "expected", hovertemplate: "expected %{y:.1f}<extra></extra>" },
      { x, y: r.v[k], mode: "lines", line: { color: css("--series-1"), width: 2 }, name: "measured", connectgaps: k === "sbp", hovertemplate: `${lab} %{y:.${dp}f} ${u}<extra></extra>` },
    ];
    if (k === "sbp") tr.push({ x, y: r.v.dbp, mode: "lines", line: { color: css("--series-3"), width: 2 }, connectgaps: true, name: "diastolic", hovertemplate: "Diastolic %{y:.0f}<extra></extra>" });
    plot(`vp_${k}`, tr, baseLayout({ margin: { l: 38, r: 8, t: 4, b: 22 }, xaxis: { gridcolor: "#2a2a28", title: { text: "" }, ticksuffix: " h" } }));
  });
  if (det.ecg) {
    const fs = det.ecg.fs / 2;
    plot("ecgPlot", [{ x: det.ecg.mv.map((_, i) => i / fs), y: det.ecg.mv, mode: "lines", line: { color: css("--series-3"), width: 1.5 }, hovertemplate: "%{y:.2f} mV<extra></extra>" }],
      baseLayout({ xaxis: { gridcolor: "#2a2a28", ticksuffix: " s" }, yaxis: { gridcolor: "#2a2a28", ticksuffix: " mV" } }));
    const pr = det.ecg.proc || {};
    $("#ecgHint").textContent = `synthetic 10-s window · SQI ${fmt(pr.quality, 2)} · beats ${pr.n_beats ?? "—"} · R-R CV ${fmt(pr.rr_cv, 3)}`;
  }
  $("#baselineTbl").innerHTML = `<tr><th>Parameter</th><th>Source</th><th>Type</th><th>Expected</th><th>Band (±2σ)</th><th>Samples</th><th>Trend /h</th></tr>` +
    Object.entries(det.baselines).map(([k, b]) => `<tr><td>${esc(b.label)}</td><td class="muted">${esc(b.sensor)}</td>
      <td>${b.measured ? '<span class="tag-m">measured</span>' : '<span class="tag-d">derived</span>'}</td>
      <td class="num">${fmt(b.expected, 1)}</td><td class="num">${fmt(b.lo, 1)} – ${fmt(b.hi, 1)}</td><td class="num">${b.n}</td>
      <td class="num">${fmt(det.slopes[k].slope_h, 2)} ±${fmt(det.slopes[k].sd_h, 2)}</td></tr>`).join("");
  const keys = ["hr", "spo2", "rr", "sbp", "temp", "hrv_rmssd"];
  $("#longTbl").innerHTML = `<tr><th>Day</th><th>Sleep h</th>${keys.map((k) => `<th>${k.toUpperCase()}</th>`).join("")}</tr>` +
    det.longitudinal.map((row) => `<tr><td class="num">${row.day}</td><td class="num">${fmt(row.sleep_h, 1)}</td>${keys.map((k) => `<td class="num">${fmt(row[k], 1)}</td>`).join("")}</tr>`).join("") +
    `<tr><td><b>Drift</b></td><td></td>${keys.map((k) => `<td class="num">${det.drift[k] ? (det.drift[k].drift >= 0 ? "+" : "") + fmt(det.drift[k].drift, 2) : "—"}</td>`).join("")}</tr>`;
  $("#timeline").innerHTML = det.timeline.length ? det.timeline.map(logLine(d)).join("") : '<p class="muted">No events yet.</p>';
}

/* ------------------------------------------------------------------ AI */
function renderAI(d) {
  const det = d.detail, r = det.recent, x = r.t.map((t) => (t - (d.t - d.demo_minute)) / 60);
  plot("mlPlot", [
    { x, y: r.anomaly, mode: "lines", name: "Anomaly score", line: { color: css("--series-1"), width: 2 }, hovertemplate: "anomaly %{y:.3f}<extra></extra>" },
    { x, y: r.risk, mode: "lines", name: "Risk forecast (30 min)", line: { color: css("--series-2"), width: 2 }, hovertemplate: "risk %{y:.3f}<extra></extra>" },
    { x: [x[0], x[x.length - 1]], y: [0.5, 0.5], mode: "lines", name: "watch threshold", line: { color: "#8d8c84", width: 1, dash: "dot" }, hoverinfo: "skip" },
  ], baseLayout({ showlegend: true, legend: { orientation: "h", y: 1.12, x: 0, font: { size: 11 } }, margin: { l: 40, r: 12, t: 26, b: 28 },
    yaxis: { gridcolor: "#2a2a28", range: [0, 1.02] }, xaxis: { gridcolor: "#2a2a28", ticksuffix: " h" } }));
  const ex = det.explanation, cls = det.classification;
  const li = (a) => a.length ? `<ul>${a.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : '<p class="muted">None.</p>';
  $("#aiExplain").innerHTML = `<div class="rep">${badge(cls.level, `L${cls.level} ${cls.label}`)} <span class="muted">candidate L${cls.candidate_level} · confidence ${cls.confidence_label} ${cls.confidence}</span>
    <h4>Reasons</h4>${li(cls.reasons)}<h4>Compared with this astronaut's own baseline</h4>${li(ex.baseline_text)}
    <h4>Significant trends</h4>${li(ex.significant_changes)}<h4>Missing / unreliable information</h4>${li(ex.missing)}
    <p class="muted">${esc(ex.note)}</p></div>`;
  const sh = (ex.influencing_parameters || []).slice().reverse();
  plot("shapPlot", sh.length ? [{ type: "bar", orientation: "h", x: sh.map((s) => s.contribution), y: sh.map((s) => `${s.feature} = ${s.value}`),
    marker: { color: sh.map((s) => (s.contribution > 0 ? css("--series-2") : css("--series-1"))) }, hovertemplate: "%{y}<br>contribution %{x:+.3f}<extra></extra>" }] : [],
    baseLayout({ margin: { l: 150, r: 12, t: 4, b: 26 }, hovermode: "closest", xaxis: { gridcolor: "#2a2a28", zeroline: true, zerolinecolor: "#55554f", title: { text: "← lowers risk · raises risk →", font: { size: 10 } } },
      annotations: sh.length ? [] : [{ text: "No forecaster output yet", showarrow: false, font: { color: "#8d8c84" } }] }));
  const cr = Object.entries(det.correlations || {});
  plot("corrPlot", cr.length ? [{ type: "bar", x: cr.map((c) => c[0].replace("~", " ~ ")), y: cr.map((c) => c[1]),
    marker: { color: cr.map((c) => (c[1] >= 0 ? css("--series-2") : css("--series-1"))) }, hovertemplate: "%{x}: r = %{y:.2f}<extra></extra>" }] : [],
    baseLayout({ hovermode: "closest", yaxis: { gridcolor: "#2a2a28", range: [-1, 1], zeroline: true, zerolinecolor: "#55554f" }, margin: { l: 34, r: 8, t: 4, b: 50 } }));
  $("#patterns").innerHTML = det.patterns.length ? det.patterns.map((p) => `<div class="logline l2">Pattern: ${esc(p.name)} — ${Object.entries(p.evidence).map(([k, v]) => `${k} z=${v}`).join(", ")}</div>`).join("")
    : '<p class="muted">No co-deviation pattern matched. Patterns are hypotheses for the CMO, never diagnoses.</p>';
  if (S.sys) {
    const s = S.sys, mm = s.model_monitoring;
    const files = Object.entries(s.models.files).map(([n, f]) => `<div class="stat"><span>${esc(n)}</span><b>${f.hash_ok ? "hash OK" : "MISMATCH"}</b></div>`).join("");
    const st = typeof s.integrity.store === "object" ? Object.entries(s.integrity.store).map(([t, v]) => `<div class="stat"><span>Local store: ${t}</span><b>${v.rows} rows · ${v.intact ? "chain intact" : "TAMPERED at " + v.first_bad_row}</b></div>`).join("") : "";
    $("#sysHealth").innerHTML = `${files}
      <div class="stat"><span>Anomaly flag rate (24 h)</span><b>${mm.anomaly_flag_rate_24h === null ? "—" : (100 * mm.anomaly_flag_rate_24h).toFixed(2) + "%"} (expected 0.5%)</b></div>
      <div class="stat"><span>Features outside training range</span><b>${mm.feature_out_of_range_frac_24h === null ? "—" : (100 * mm.feature_out_of_range_frac_24h).toFixed(2) + "%"}</b></div>
      ${mm.anomaly_drift_warning ? '<div class="logline l2">Drift warning: flag rate far above nominal — retrain/recalibrate</div>' : ""}
      ${st}<div class="stat"><span>Knowledge base</span><b>${esc(s.integrity.kb_status.split(" - ")[0])}</b></div>
      <div class="stat"><span>Edge tick latency</span><b>${s.tick_ms} ms</b></div>
      <p class="muted">Onboard: ${esc(s.edge.components_onboard.join(", "))}. Earth-side: ${esc(s.edge.earth_side.join(", "))}.</p>`;
  }
}

/* ------------------------------------------------------------------ emergency */
function renderEmergency(d) {
  $("#incList").innerHTML = d.incidents.length ? d.incidents.map((i) => incLi(i, d)).join("") : '<p class="muted">No incidents this session. Trigger one from Mission Simulation.</p>';
  $$("#incList .li").forEach((el) => el.onclick = () => { S.inc = +el.dataset.id; renderEmergency(S.data); loadReport(); });
  if (S.inc === null && d.incidents.length) { S.inc = d.incidents[0].id; }
  const rep = S.inc !== null ? d.active_reports[String(S.inc)] : null;
  if (rep) renderReport(rep, d.incidents.find((i) => i.id === S.inc));
  else if (S.inc !== null && !S.loaded) loadReport();
  $("#commTbl").innerHTML = `<tr><th>#</th><th>Priority</th><th>Kind</th><th>Summary</th><th>Status</th><th>Created</th><th>Arrives Earth</th><th>Earliest reply</th></tr>` +
    d.comms.map((m) => `<tr><td class="num">${m.id}</td><td>P${m.priority}</td><td>${esc(m.kind)}</td><td>${esc(m.summary)}</td><td>${esc(m.status)}</td>
      <td class="num">${tRel(d, m.created_min)}</td><td class="num">${m.arrive_min === null ? "—" : tRel(d, m.arrive_min)}</td><td class="num">${m.earliest_reply_min === null ? "—" : tRel(d, m.earliest_reply_min)}</td></tr>`).join("");
}
async function loadReport() {
  if (S.inc === null) return;
  S.loaded = true;
  try { const r = await api(`/api/report/${S.inc}`); if (r.report) renderReport(r.report, r.incident); } catch (e) { /* closed incident without report */ }
}
function renderReport(rep, inc) {
  const li = (a) => (a && a.length ? `<ul>${a.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : '<p class="muted">—</p>');
  const meas = (rep.abnormal_measurements || []).map((m) => `<tr><td>${esc(m.parameter)} <span class="${m.source === "measured" ? "tag-m" : "tag-d"}">${m.source}</span></td>
     <td class="num">${m.value} ${esc(m.unit)}</td><td class="num">${m.personal_expected}</td><td class="num">${m.personal_band_2sd.join(" – ")}</td>
     <td class="num">${m.z ?? "—"}</td><td class="num">${m.sustained_min} min</td><td class="num">${m.signal_quality}</td></tr>`).join("");
  const protos = (rep.recommended_protocols || []).map((p) => `<div class="proto"><b>[${esc(p.id)}] ${esc(p.title)}</b><span class="unapproved">${esc(p.approval)}</span>
     <ol>${p.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol><div class="muted">Escalate if: ${esc([].concat(p.escalation || []).join("; "))}</div>
     <div class="src">Source: ${esc(p.source.title)}${p.source.url ? ` — ${esc(p.source.url)}` : ""}</div></div>`).join("");
  const mc = rep.mission_context;
  $("#report").innerHTML = `<div class="rep">
    <div class="ev">${esc(rep.event)}</div>
    ${badge(rep.level, `L${rep.level} ${rep.level_label}`)} ${rep.astronaut ? `<b>${esc(rep.astronaut.name)}</b> <span class="muted">${esc(rep.astronaut.role)}</span>` : ""}
    ${inc && inc.closed === null ? `<button class="btn ${inc.acknowledged ? "" : "danger"}" id="ackBtn" style="float:right">${inc.acknowledged ? "Acknowledged" : "Acknowledge"}</button>` : ""}
    ${rep.detection_confidence ? `<p class="muted">Detection confidence: ${rep.detection_confidence.label} (${rep.detection_confidence.score})</p>` : ""}
    ${meas ? `<h4>Abnormal measurements vs personal baseline</h4><table class="tbl"><tr><th>Parameter</th><th>Value</th><th>Usual</th><th>Band</th><th>z</th><th>Sustained</th><th>Quality</th></tr>${meas}</table>` : ""}
    <h4>Why ARES raised this</h4>${li(rep.reasons)}
    ${rep.potential_risk_category ? `<h4>Potential risk category (hypothesis, not diagnosis)</h4>${li(rep.potential_risk_category)}` : ""}
    ${rep.additional_measurements_required ? `<h4>Additional measurements required</h4>${li(rep.additional_measurements_required)}` : ""}
    <h4>Approved-protocol retrieval (verbatim from knowledge base)</h4>${protos || '<p class="muted">—</p>'}
    <h4>Notification &amp; communication</h4>
    <div class="stat"><span>Crew notification</span><b>${esc(rep.crew_notification)}</b></div>
    <div class="stat"><span>Earth communication priority</span><b>${esc(rep.earth_communication_priority)}</b></div>
    ${mc ? `<div class="ctxbox"><b>Mission context:</b> link ${esc(mc.comm_mode)}, one-way delay ${mc.one_way_delay_min} min. ${esc(mc.guidance)}</div>` : ""}
    ${rep.model_outputs ? `<h4>Model outputs</h4><div class="stat"><span>Anomaly score</span><b>${rep.model_outputs.anomaly_score ?? "—"}</b></div>
      <div class="stat"><span>Risk forecast (30 min)</span><b>${rep.model_outputs.risk_forecast_30min ?? "—"}</b></div>
      <div class="stat"><span>NEWS2 (reference, rest/sleep only)</span><b>${rep.model_outputs.news2 ? rep.model_outputs.news2.score + " (" + rep.model_outputs.news2.risk + ")" : "—"}</b></div>
      <p class="muted">${esc(rep.model_outputs.risk_note)}</p>` : ""}
    <p class="muted">${esc(rep.disclaimer || "")}</p></div>`;
  const b = $("#ackBtn");
  if (b) b.onclick = async () => { await api("/api/ack", { incident_id: inc.id }); refresh(); };
}

/* ------------------------------------------------------------------ behavioral & clinical */
function renderBehavioral(d) {
  const bv = d.detail.behavioral, a = bv.assessment, s = bv.series;
  $("#behStatus").innerHTML = `${badge(a.level, a.label)} <span class="muted">${esc(a.visibility)}</span>
    ${Object.entries(a.domains).map(([k, v]) => `<div class="stat"><span>${k}</span><b style="font-family:var(--sans);font-weight:500">${v.flag ? "▲ " : ""}${esc(v.text)}</b></div>`).join("")}
    <p class="muted">${esc(a.note)} Earth receives only: “${esc(a.earth_summary)}”.</p>`;
  const live = s.sources;
  plot("behPlot", [{ x: s.pvt_day, y: s.speed, mode: "lines+markers", line: { color: css("--series-1"), width: 2 }, marker: { size: 8, line: { color: css("--panel"), width: 2 } },
    hovertemplate: "day %{x:.1f}: speed %{y:.2f}/s<extra></extra>" }],
    baseLayout({ yaxis: { gridcolor: "#2a2a28", title: { text: "PVT-B response speed (1/s)", font: { size: 10 } } }, xaxis: { gridcolor: "#2a2a28", title: { text: "mission day", font: { size: 10 } } }, hovermode: "closest" }));
  const cl = d.detail.clinical;
  if (!$("#symptomBox").children.length) {
    $("#symptomBox").innerHTML = cl.symptom_options.map((o) => `<span class="chip" data-s="${o}">${o.replace(/_/g, " ")}</span>`).join("");
    $$("#symptomBox .chip").forEach((c) => c.onclick = () => { c.classList.toggle("on"); c.classList.contains("on") ? S.sym.add(c.dataset.s) : S.sym.delete(c.dataset.s); });
    $("#labForm").innerHTML = Object.entries(cl.lab_fields).map(([k, f]) => `<label>${esc(f.label)} (${esc(f.unit)})<input type="number" step="0.01" name="${k}"><span class="muted" id="pre_${k}"></span></label>`).join("")
      + '<button class="btn" type="submit">Record lab results</button>';
    $("#labForm").onsubmit = async (e) => {
      e.preventDefault();
      const v = {}; new FormData(e.target).forEach((val, k) => { if (val !== "") v[k] = +val; });
      await api(`/api/clinical/${S.sel}/labs`, v); e.target.reset(); refresh();
    };
  }
  Object.keys(cl.lab_fields).forEach((k) => { const el = $(`#pre_${k}`); if (el) el.textContent = `own pre-flight: ${(cl.preflight || cl.labs.preflight || {})[k] ?? "—"} · generic ${cl.lab_fields[k].range.join("–")}`; });
  $("#labStatus").innerHTML = `<div class="stat"><span>Symptoms reported (24 h)</span><b>${esc(cl.active_symptoms_24h.join(", ").replace(/_/g, " ") || "none")}</b></div>` +
    (cl.labs.flags || []).map((f) => `<div class="logline l1">▲ ${esc(f)}</div>`).join("") +
    `<p class="muted">${esc(cl.labs.note || "No in-flight lab results yet. Pre-flight values are SIMULATED.")}</p>`;
}

/* PVT-B: real reaction-time test in the browser */
function pvtStart(seconds) {
  if (S.pvt) return;
  const box = $("#pvtBox");
  const st = { end: performance.now() + seconds * 1000, rts: [], antic: 0, shownAt: null, timer: null, tick: null, seconds };
  S.pvt = st; box.focus();
  const next = () => {
    if (performance.now() > st.end) return finish();
    box.classList.remove("go"); box.textContent = "";
    st.timer = setTimeout(() => {
      st.shownAt = performance.now(); box.classList.add("go");
      st.tick = setInterval(() => { box.textContent = Math.round(performance.now() - st.shownAt); }, 20);
      st.timer = setTimeout(() => { respond(true); }, 10000);   // no response -> 10 s lapse cap
    }, 2000 + Math.random() * 3000);   // inter-stimulus interval 2-5 s
  };
  const respond = (timeout) => {
    if (st.shownAt === null) { if (!timeout) st.antic++; return; }
    const rt = performance.now() - st.shownAt;
    clearInterval(st.tick); clearTimeout(st.timer); st.shownAt = null;
    st.rts.push(rt); box.textContent = `${Math.round(rt)} ms`;
    $("#pvtInfo").textContent = `${st.rts.length} responses · ${st.antic} false starts · ${Math.max(0, Math.round((st.end - performance.now()) / 1000))} s left`;
    setTimeout(next, 400);
  };
  const finish = async () => {
    clearInterval(st.tick); clearTimeout(st.timer);
    box.classList.remove("go"); box.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey);
    S.pvt = null; box.textContent = "Scoring…";
    const r = await api(`/api/behavioral/${S.sel}/pvt`, { rts_ms: st.rts, anticipations: st.antic });
    const x = r.result;
    box.innerHTML = r.ok ? `Response speed <b>${x.response_speed}/s</b> · mean RT ${x.mean_rt_ms} ms · lapses (≥355 ms) <b>${x.lapses}</b> · false starts ${x.false_starts}<br><span class="muted">${seconds < 180 ? "Shortened demo run — a valid PVT-B is 3 min." : "Scored as PVT-B."} Saved to the private record.</span>`
      : `Not scored: ${esc(x.reason)}`;
    refresh();
  };
  const onDown = (e) => { e.preventDefault(); respond(false); };
  const onKey = (e) => { if (e.code === "Space") { e.preventDefault(); respond(false); } };
  box.addEventListener("pointerdown", onDown); document.addEventListener("keydown", onKey);
  next();
}

/* ------------------------------------------------------------------ simulation */
function renderSim(d) {
  if (!$("#scenarioGrid").children.length) {
    $("#scenarioGrid").innerHTML = d.scenarios.map((s) => `<button type="button" class="scen" data-k="${s.key}">
      <span class="scen-state"></span><b>${esc(s.name)}</b><p>${esc(s.description)}</p></button>`).join("");
    $$("#scenarioGrid .scen").forEach((el) => el.onclick = () => injectScenario(el));
  }
  // highlight scenarios that are running, and show who they target
  const act = {};
  d.active_scenarios.forEach((a) => { (act[a.key] = act[a.key] || []).push(who(d, a.astronaut_id)); });
  $$("#scenarioGrid .scen").forEach((el) => {
    const on = act[el.dataset.k];
    el.classList.toggle("active", !!on);
    if (!el.classList.contains("busy")) el.querySelector(".scen-state").textContent = on ? `● ACTIVE → ${on.join(", ")}` : "";
  });
  $("#scenTarget").textContent = who(d, S.sel);
  $("#activeScen").textContent = d.active_scenarios.length ? "Active: " + d.active_scenarios.map((s) => `${s.name} → ${who(d, s.astronaut_id)}`).join(" · ") : "No scenario active (nominal).";
  const mode = d.mission.comm_reason === "operator override" ? d.mission.comm_mode : "";
  $$("#commSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("#shelterBtn").textContent = d.shelter ? "Leave shelter" : "Enter shelter";
  $("#pauseBtn").textContent = d.runtime.paused ? "Resume" : "Pause";
  if (!S.speedSynced) { $("#speed").value = d.runtime.speed; $("#speedOut").textContent = `${d.runtime.speed} min/s`; S.speedSynced = true; }
}
async function injectScenario(el) {
  if (el.classList.contains("busy")) return;
  const name = el.querySelector("b").textContent, target = who(S.data, S.sel);
  el.classList.add("busy");
  el.querySelector(".scen-state").textContent = "Injecting…";
  try {
    const r = await api("/api/scenario", { key: el.dataset.k, astronaut_id: S.sel });
    const crewWide = /CO2|Radiation|radiation/.test(name);
    toast(`Injected: ${r.scenario} → ${crewWide ? "whole crew" : target}. Watch Mission Overview / Emergency Command.`, "ok");
    addChat(`[SIMULATION] Injected: ${r.scenario}`, [{ title: "Target", items: [crewWide ? "Whole crew" : target], source: "scenario library (synthetic)" }]);
  } catch (e) {
    toast(`Could not inject "${name}": the ARES server did not respond (${e.message}). Is the terminal still running?`, "err");
  } finally {
    el.classList.remove("busy");
    refresh();
  }
}
let toastTimer = null;
function toast(msg, kind = "ok") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast"; }, kind === "err" ? 9000 : 5000);
}
function addChat(q, sections) {
  const box = $("#chat");
  const sec = sections.map((s) => `<div class="msg-s"><b>${esc(s.title)}</b>${(s.items || []).map((it) => typeof it === "string" ? `<div>• ${esc(it)}</div>`
    : `<div class="proto"><b>[${esc(it.id)}] ${esc(it.title)}</b> <span class="muted">match ${it.score}</span><ol>${it.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</ol><div class="src">${esc(it.citation)}</div></div>`).join("")}
    <div class="src">Source: ${esc(s.source || "")}</div></div>`).join("");
  box.insertAdjacentHTML("beforeend", `<div class="msg-q">${esc(q)}</div>${sec}`);
  box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------------ wiring */
function switchTab(t) {
  S.tab = t;
  $$("#tabs button[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${t}`));
  if (S.data) render(S.data);
  window.dispatchEvent(new Event("resize"));
}
function setSel(aid) { S.sel = aid; $("#crewSelect").value = aid; refresh(); }
function render(d) {
  renderHeader(d);
  const f = { overview: renderOverview, twin: renderTwin, ai: renderAI, emergency: renderEmergency, behavioral: renderBehavioral, sim: renderSim }[S.tab];
  try { f(d); } catch (e) { console.error(e); }
}
async function refresh() {
  if (S.busy) return;
  S.busy = true;
  try {
    const d = await api(`/api/state${S.sel ? `?astronaut=${S.sel}` : ""}`);
    S.data = d;
    if (!S.sel) {
      S.sel = d.selected;
      $("#crewSelect").innerHTML = d.crew.map((c) => `<option value="${c.id}">${esc(c.name)} — ${esc(c.role)}</option>`).join("");
    }
    render(d);
  } catch (e) { $("#footer").textContent = "Connection to the local ARES service lost — retrying…"; }
  S.busy = false;
}
async function refreshSys() { if (S.tab === "ai") { try { S.sys = await api("/api/system"); } catch (e) { /* ignore */ } } }

document.addEventListener("DOMContentLoaded", () => {
  $$("#tabs button[data-tab]").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));
  $("#crewSelect").onchange = (e) => setSel(e.target.value);
  $("#clearScen").onclick = async () => {
    try { await api("/api/clear", {}); toast("All scenarios cleared - crew returning to nominal (incidents close after hysteresis).", "ok"); }
    catch (e) { toast(`Server did not respond (${e.message}).`, "err"); }
    refresh();
  };
  $$("#commSeg button").forEach((b) => b.onclick = async () => {
    try { await api("/api/comm", { mode: b.dataset.mode || null }); toast(`Earth link: ${b.textContent}`, "ok"); }
    catch (e) { toast(`Server did not respond (${e.message}).`, "err"); }
    refresh();
  });
  $("#speed").oninput = (e) => { $("#speedOut").textContent = `${e.target.value} min/s`; };
  $("#speed").onchange = async (e) => { await api("/api/speed", { minutes_per_second: +e.target.value }); };
  $("#pauseBtn").onclick = async () => { await api("/api/speed", { minutes_per_second: +$("#speed").value, paused: !S.data.runtime.paused }); refresh(); };
  $("#shelterBtn").onclick = async () => { await api("/api/shelter", { on: !S.data.shelter }); refresh(); };
  $("#dayBtn").onclick = async () => { await api("/api/mission_day", { day: +$("#dayInput").value }); refresh(); };
  $("#askForm").onsubmit = async (e) => {
    e.preventDefault();
    const q = $("#askInput").value.trim(); if (!q) return;
    $("#askInput").value = "";
    const r = await api("/api/assistant", { question: q, astronaut_id: S.sel });
    addChat(q, r.sections.concat([{ title: "Note", items: [r.disclaimer], source: "retrieval-only assistant" }]));
  };
  $("#pvtStart").onclick = () => pvtStart(180);
  $("#pvtShort").onclick = () => pvtStart(90);
  $$("#checkinForm input[type=range]").forEach((i) => i.oninput = () => { i.nextElementSibling.textContent = i.value; });
  $("#checkinForm").onsubmit = async (e) => {
    e.preventDefault();
    const v = {}; new FormData(e.target).forEach((val, k) => { v[k] = +val; });
    await api(`/api/behavioral/${S.sel}/checkin`, v); refresh();
  };
  $("#symSubmit").onclick = async () => {
    if (!S.sym.size) return;
    await api(`/api/clinical/${S.sel}/symptoms`, { symptoms: [...S.sym] });
    S.sym.clear(); $$("#symptomBox .chip").forEach((c) => c.classList.remove("on")); refresh();
  };
  const h = location.hash.replace("#", "");
  if (h && document.getElementById(`tab-${h}`)) switchTab(h);
  refresh(); refreshSys();
  setInterval(refresh, 1000);
  setInterval(refreshSys, 4000);
});
