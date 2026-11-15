"""Prioritised store-and-forward Earth communication queue.

P1 critical > P2 priority > P3 next window > P4 routine. When the link is
up, the highest-priority messages go first (limited messages per minute to
represent bandwidth). Arrival at Earth = send time + one-way light time; the
earliest possible ground reply = send time + round trip (+ ground handling).
In blackout everything waits in the queue; nothing is dropped.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass

GROUND_HANDLING_MIN = 5.0
MSGS_PER_MIN = 2


@dataclass
class Message:
    id: int
    priority: int
    created_min: float
    kind: str
    summary: str
    astronaut_id: str | None = None
    status: str = "queued"        # queued -> in_transit -> delivered -> ground_reply_due
    waiting_note: str | None = None   # why it has not been sent yet (e.g. Earth link down)
    attempts: int = 0
    sent_min: float | None = None
    arrive_min: float | None = None
    earliest_reply_min: float | None = None


class CommQueue:
    def __init__(self):
        self._ids = itertools.count(1)
        self.messages: list[Message] = []

    def enqueue(self, priority: int, t: float, kind: str, summary: str, astronaut_id: str | None = None) -> Message:
        # de-duplicate: an identical message still waiting in the queue is not added twice
        for q in self.messages:
            if q.status == "queued" and q.kind == kind and q.summary == summary:
                q.priority = min(q.priority, priority)
                return q
        m = Message(next(self._ids), priority, t, kind, summary, astronaut_id)
        self.messages.append(m)
        return m

    def step(self, t: float, mode: str, owlt_min: float) -> None:
        if mode == "blackout":
            for m in self.messages:
                if m.status == "queued":
                    m.waiting_note = "Earth link down - stored onboard, will send automatically"
        else:
            queued = sorted([m for m in self.messages if m.status == "queued"], key=lambda m: (m.priority, m.created_min))
            for m in queued[MSGS_PER_MIN:]:
                m.waiting_note = "waiting for bandwidth (higher-priority messages first)"
            for m in queued[:MSGS_PER_MIN]:
                m.attempts += 1
                m.waiting_note = None
                m.status, m.sent_min = "in_transit", t
                m.arrive_min = t + owlt_min
                m.earliest_reply_min = t + 2 * owlt_min + GROUND_HANDLING_MIN
        for m in self.messages:
            if m.status == "in_transit" and t >= (m.arrive_min or 0):
                m.status = "delivered"
            if m.status == "delivered" and t >= (m.earliest_reply_min or 0):
                m.status = "ground_reply_due"
        self.messages = [m for m in self.messages if not (m.status == "ground_reply_due" and t - (m.earliest_reply_min or 0) > 240)]

    def snapshot(self, limit: int = 40) -> list[dict]:
        ms = sorted(self.messages, key=lambda m: (m.status != "queued", m.priority, -m.created_min))
        return [asdict(m) for m in ms[:limit]]

    def stats(self, t: float) -> dict:
        by = {}
        for m in self.messages:
            by[m.status] = by.get(m.status, 0) + 1
        q = [m for m in self.messages if m.status == "queued"]
        return {"by_status": by, "queued": len(q), "critical_queued": sum(m.priority == 1 for m in q),
                "oldest_queued_min": round(t - min(m.created_min for m in q), 1) if q else None,
                "delivered": by.get("delivered", 0) + by.get("ground_reply_due", 0), "failed": 0,
                "policy": "priority order (P1 first), duplicates merged, timestamps preserved, nothing dropped in blackout"}

    def pending(self) -> int:
        return sum(m.status == "queued" for m in self.messages)
