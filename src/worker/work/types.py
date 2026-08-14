"""Work protocol: intent signal, decision, events, and status machine."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class WorkStatus(str, Enum):
    detected = "detected"
    pending_confirmation = "pending_confirmation"
    declined = "declined"
    fallback_to_speak = "fallback_to_speak"
    starting = "starting"
    running = "running"
    finished = "finished"
    failed = "failed"
    aborted = "aborted"


# Minimal allowed transitions — no arbitrary jumps.
ALLOWED_TRANSITIONS: dict[WorkStatus, frozenset[WorkStatus]] = {
    WorkStatus.detected: frozenset({WorkStatus.pending_confirmation, WorkStatus.declined}),
    WorkStatus.pending_confirmation: frozenset({
        WorkStatus.declined,
        WorkStatus.fallback_to_speak,
        WorkStatus.starting,
        WorkStatus.aborted,
    }),
    WorkStatus.declined: frozenset(),
    WorkStatus.fallback_to_speak: frozenset(),
    WorkStatus.starting: frozenset({
        WorkStatus.running,
        WorkStatus.failed,
        WorkStatus.aborted,
    }),
    WorkStatus.running: frozenset({
        WorkStatus.finished,
        WorkStatus.failed,
        WorkStatus.aborted,
    }),
    WorkStatus.finished: frozenset(),
    WorkStatus.failed: frozenset(),
    WorkStatus.aborted: frozenset(),
}


TERMINAL_STATUSES = frozenset({
    WorkStatus.declined,
    WorkStatus.fallback_to_speak,
    WorkStatus.finished,
    WorkStatus.failed,
    WorkStatus.aborted,
})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkIntentSignal:
    work_id: str
    session_id: str
    channel_id: str
    gen_id: str
    question: str
    matched_terms: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkDecision:
    work_id: str
    decision: str  # needs_work | declined | insufficient
    reason: str = ""
    reason_code: str = ""
    fallback_to_speak: bool = True
    suggested_action: str = ""
    requires_user_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkEvent:
    type: str
    work_id: str
    status: str
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    seq: int = 0
    reason: str = ""
    reason_code: str = ""

    def to_ws_dict(self, *, gen_id: str = "", session_id: str = "") -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "work_id": self.work_id,
            "status": self.status,
            "message": self.message,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "seq": self.seq,
        }
        if self.reason:
            data["reason"] = self.reason
        if self.reason_code:
            data["reason_code"] = self.reason_code
        if gen_id:
            data["gen_id"] = gen_id
        if session_id:
            data["session_id"] = session_id
        return data


@dataclass
class WorkRecord:
    signal: WorkIntentSignal
    status: WorkStatus = WorkStatus.detected
    decision: WorkDecision | None = None
    events: list[WorkEvent] = field(default_factory=list)
    seq: int = 0
    answer: str = ""
    error: str = ""
    monitor: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    abort_requested: bool = False

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def summary_dict(self) -> dict[str, Any]:
        return {
            "work_id": self.signal.work_id,
            "status": self.status.value,
            "question": self.signal.question,
            "matched_terms": list(self.signal.matched_terms),
            "reason": (self.decision.reason if self.decision else "") or self.error,
            "reason_code": self.decision.reason_code if self.decision else "",
            "answer": self.answer,
            "monitor": dict(self.monitor),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "created_at": self.signal.created_at,
            "events": [
                {
                    "type": e.type,
                    "status": e.status,
                    "message": e.message,
                    "seq": e.seq,
                    "reason": e.reason,
                    "reason_code": e.reason_code,
                    "payload": e.payload,
                    "created_at": e.created_at,
                }
                for e in self.events
            ],
        }
