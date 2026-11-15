"""Incident-management workflow for the Emergency Command Center.

Ten steps; some are completed automatically by ARES, the rest by crew actions that really change engine state:

 1 detect      auto   incident opened by the classifier
 2 verify      crew   request measurements -> record outcome (confirmed / sensor issue)
 3 assess      auto   severity level from the classifier (manual escalation can raise it)
 4 notify      crew   mark the crew / CMO notified
 5 protocol    auto   approved protocol retrieved from the local knowledge base
 6 acknowledge crew   alert acknowledged
 7 monitor     crew   start follow-up monitoring (extends post-event monitoring, logged every check)
 8 escalate    crew   optional: raise the level floor, P1 message to Earth
 9 earth       auto   report queued in the store-and-forward Earth queue (sync status shown)
10 close       crew   allowed only once physiology is back to normal (or the environmental event has ended)
"""

from __future__ import annotations

STEPS = [("detect", "Detect abnormality"), ("verify", "Verify measurements"), ("assess", "Assess severity"),
         ("notify", "Notify crew"), ("protocol", "Retrieve approved protocol"), ("acknowledge", "Record crew acknowledgement"),
         ("monitor", "Monitor the astronaut"), ("escalate", "Escalate if necessary"), ("earth", "Queue report for Earth"),
         ("close", "Close after review")]
ACTIONS = {"request_measurements", "verify_confirmed", "verify_sensor_issue", "notify_crew", "acknowledge",
           "start_followup", "escalate", "queue_earth", "close"}
PRIORITY_BY_LEVEL = {0: 4, 1: 3, 2: 2, 3: 1}


def wf(inc: dict) -> dict:
    return inc.setdefault("wf", {"events": [], "verify": None, "notify": None, "monitor": None, "escalated": None,
                                 "requests": [], "closed_review": None, "reports": 0, "earth_ids": []})


def _ev(inc, t, actor, text, kind="action"):
    wf(inc)["events"].append({"t": t, "actor": actor, "text": text, "kind": kind})


def _who(engine, aid):
    return engine.by_id[aid].name if aid in engine.by_id else {"ENV": "Radiation environment",
                                                               "CABIN": "Cabin environment"}.get(aid, aid)


def _msgs(engine, inc):
    tag = f"#{inc['id']} "
    return [m for m in engine.comms.snapshot(limit=500) if m["summary"].startswith(tag)]


def status_of(inc: dict) -> str:
    w = wf(inc)
    if w["closed_review"]:
        return "closed"
    if inc["closed"] is not None:
        return "resolved - awaiting review"
    return "active"


def view(engine, inc: dict) -> dict:
    w = wf(inc)
    t = engine.t
    rep = inc.get("report") or {}
    msgs = _msgs(engine, inc)
    st = status_of(inc)
    still = inc["closed"] is None
    steps = {
        "detect": ("done", inc["opened"], "ARES", f"L{inc['history'][0][1]} raised by the classifier"),
        "verify": (("done", w["verify"]["t"], "crew", w["verify"]["text"]) if w["verify"] else
                   ("active", w["requests"][-1]["t"], "crew", "Measurements requested - waiting for result")
                   if w["requests"] else ("pending", None, None, "Re-measure to confirm before acting")),
        "assess": ("done", inc["history"][-1][0], "ARES", f"Current L{inc['level']}, peak L{inc['peak_level']}"),
        "notify": (("done", w["notify"]["t"], "crew", "Crew and medical officer notified") if w["notify"] else
                   ("pending", None, None, "Tell the crew / medical officer")),
        "protocol": (("done", inc["opened"], "ARES", ", ".join(p["id"] for p in rep.get("recommended_protocols", [])))
                     if rep.get("recommended_protocols") else ("pending", None, None, "Waiting for report")),
        "acknowledge": (("done", None, "crew", "Alert acknowledged") if inc.get("acknowledged") else
                        ("pending", None, None, "Acknowledge the alert")),
        "monitor": (("active" if still or (w["monitor"] and t < w["monitor"]["until"]) else "done", w["monitor"]["t"],
                     "crew", f"Follow-up checks every {w['monitor']['every_min']} min until "
                             f"T+{(w['monitor']['until'] - engine.baseline_end) / 60:.1f} h")
                    if w["monitor"] else ("pending", None, None, "Start follow-up monitoring")),
        "escalate": (("done", w["escalated"]["t"], "crew", w["escalated"]["text"]) if w["escalated"] else
                     ("optional", None, None, "Only if the situation worsens or protocol criteria are met")),
        "earth": (("done", msgs[-1]["created_min"], "ARES",
                   f"{len(msgs)} message(s): " + ", ".join(sorted({m['status'] for m in msgs})))
                  if msgs else ("pending", None, None, "Queue a report for Earth")),
        "close": (("done", w["closed_review"]["t"], "crew", "Closed after review") if w["closed_review"] else
                  ("ready", None, None, "Physiology back to normal - review and close") if not still else
                  ("pending", None, None, "Can close once the condition has resolved")),
    }
    events = [{"t": tt, "actor": "ARES", "text": f"Severity L{lv}" + (" (opened)" if i == 0 else ""), "kind": "level"}
              for i, (tt, lv) in enumerate(inc["history"])]
    if inc["closed"] is not None:
        events.append({"t": inc["closed"], "actor": "ARES", "text": "Measurements back to normal - incident resolved",
                       "kind": "level"})
    events += [{"t": m["created_min"], "actor": "ARES", "text": f"Earth queue: P{m['priority']} {m['kind']} ({m['status']})",
                "kind": "comm"} for m in msgs]
    events += w["events"]
    events.sort(key=lambda e: e["t"])
    return {
        "id": inc["id"], "astronaut_id": inc["astronaut_id"], "astronaut": _who(engine, inc["astronaut_id"]),
        "opened": inc["opened"], "closed": inc["closed"], "level": inc["level"], "peak_level": inc["peak_level"],
        "status": st, "acknowledged": inc.get("acknowledged", False), "event": rep.get("event"),
        "minutes_since": round(t - inc["opened"], 1), "escalated": bool(w["escalated"]),
        "steps": [{"key": k, "label": lab, "state": steps[k][0], "t": steps[k][1], "by": steps[k][2],
                   "detail": steps[k][3]} for k, lab in STEPS],
        "timeline": events, "requests": w["requests"], "reports_generated": w["reports"],
        "earth_messages": msgs,
    }


def act(engine, inc: dict, action: str, note: str | None = None) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"unknown action '{action}'")
    w = wf(inc)
    t = engine.t
    aid = inc["astronaut_id"]
    name = _who(engine, aid)
    if w["closed_review"]:
        raise ValueError("incident is closed")
    if action == "request_measurements":
        rep = inc.get("report") or {}
        items = rep.get("additional_measurements_required") or ["Repeat the triggering measurement with a backup device"]
        w["requests"].append({"t": t, "items": items})
        _ev(inc, t, "crew", "Additional measurements requested: " + "; ".join(items))
        engine.twins.get(aid) and engine.twins[aid].add_event(t, "action", f"#{inc['id']}: measurements requested", 0)
    elif action in ("verify_confirmed", "verify_sensor_issue"):
        txt = ("Re-measurement CONFIRMS the abnormal reading" if action == "verify_confirmed"
               else "Re-measurement suggests a SENSOR problem - sensor to be re-seated / replaced")
        w["verify"] = {"t": t, "text": txt, "outcome": action}
        _ev(inc, t, "crew", txt)
    elif action == "notify_crew":
        w["notify"] = {"t": t}
        _ev(inc, t, "crew", "Crew and medical officer notified")
    elif action == "acknowledge":
        engine.acknowledge(inc["id"])
        _ev(inc, t, "crew", "Alert acknowledged")
    elif action == "start_followup":
        every = 15 if inc["level"] >= 2 else 30
        w["monitor"] = {"t": t, "every_min": every, "until": t + 180}
        if aid in engine.post_event_until:
            engine.post_event_until[aid] = max(engine.post_event_until[aid], t + 180)
        elif aid in engine.by_id:
            engine.post_event_until[aid] = t + 180
        _ev(inc, t, "crew", f"Follow-up monitoring started: checks every {every} min for 3 h")
    elif action == "escalate":
        new = min(3, max(inc["level"], inc["peak_level"]) + (1 if inc["level"] < 3 else 0))
        inc["floor"] = new
        inc["level"] = max(inc["level"], new)
        inc["peak_level"] = max(inc["peak_level"], new)
        inc["history"].append((t, inc["level"]))
        inc["acknowledged"] = False
        w["escalated"] = {"t": t, "text": f"Escalated by crew to L{new}" + (f": {note}" if note else "")}
        engine.comms.enqueue(PRIORITY_BY_LEVEL[new], t, "escalation", f"#{inc['id']} {name}: ESCALATED to L{new} by crew", aid)
        engine._log(f"{name}: incident #{inc['id']} escalated by crew to L{new}", new)
        _ev(inc, t, "crew", w["escalated"]["text"])
    elif action == "queue_earth":
        rep = inc.get("report") or {}
        summary = f"#{inc['id']} {name}: report update - L{inc['level']} {rep.get('event', '')}"[:160]
        m = engine.comms.enqueue(PRIORITY_BY_LEVEL[inc["level"]], t, "incident_report", summary, aid)
        _ev(inc, t, "crew", f"Report queued for Earth (P{m.priority}, message {m.id})")
    elif action == "close":
        if inc["closed"] is None:
            still = engine.last.get(aid, {}).get("cls", {}).get("level", 0) if aid in engine.by_id else 1
            if aid in ("ENV", "CABIN") or still > 0:
                raise ValueError("still abnormal - keep monitoring or escalate; close is allowed once readings are normal")
            inc["closed"] = t
            inc["level"] = 0
            engine.active.pop(aid, None)
        inc.pop("floor", None)
        w["closed_review"] = {"t": t, "note": note}
        _ev(inc, t, "crew", "Incident closed after review" + (f": {note}" if note else ""))
        engine._log(f"Incident #{inc['id']} ({name}) closed after crew review")
    return view(engine, inc)


def report_markdown(engine, inc: dict) -> str:
    w = wf(inc)
    w["reports"] += 1
    v = view(engine, inc)
    rep = inc.get("report") or {}
    T = lambda m: f"T+{(m - engine.baseline_end) / 60:.2f} h"  # noqa: E731
    L = [f"# ARES incident report #{inc['id']}", "",
         f"- Astronaut: {v['astronaut']}  ", f"- Event: {rep.get('event', '-')}  ",
         f"- Opened: {T(inc['opened'])}; status: {v['status']}; current level L{inc['level']}, peak L{inc['peak_level']}  ",
         f"- Generated: {T(engine.t)} (mission clock); data are SIMULATED (research prototype)", "",
         "## Why ARES raised this"] + [f"- {r}" for r in rep.get("reasons", [])] + ["", "## Measurements vs personal baseline",
         "| Parameter | Value | Usual | z | Sustained |", "|---|---|---|---|---|"]
    for m in rep.get("abnormal_measurements", []):
        L.append(f"| {m['parameter']} | {m['value']} {m['unit']} | {m['personal_expected']} | {m.get('z', '-')} | {m['sustained_min']} min |")
    L += ["", "## Protocols retrieved (verbatim, DEMO knowledge base)"]
    for p in rep.get("recommended_protocols", []):
        L.append(f"### [{p['id']}] {p['title']} ({p['approval']})")
        L += [f"{i + 1}. {s}" for i, s in enumerate(p["steps"])]
        L.append(f"Source: {p['source']['title']}")
    L += ["", "## Workflow"] + [f"- [{'x' if s['state'] == 'done' else ' '}] {s['label']}: {s['detail']}" for s in v["steps"]]
    L += ["", "## Event timeline"] + [f"- {T(e['t'])} [{e['actor']}] {e['text']}" for e in v["timeline"]]
    L += ["", "_ARES is decision support only; it does not diagnose or prescribe._"]
    _ev(inc, engine.t, "crew", "Emergency report generated")
    return "\n".join(L) + "\n"
