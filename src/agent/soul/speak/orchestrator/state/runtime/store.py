from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from ..core.delivery import DeliveryPlan
from ..core.outline import DialogueOutline, RhythmState
from ..core.poll import PollCursor


@dataclass
class SessionSchedulingState:
    session_id: str
    outline: DialogueOutline = field(default_factory=DialogueOutline)
    rhythm: RhythmState = field(default_factory=RhythmState)
    poll_cursors: dict[str, PollCursor] = field(default_factory=dict)
    delivery_plan: DeliveryPlan | None = None
    pending_delivery_plan: DeliveryPlan | None = None
    user_intent: str = ""
    user_intent_confidence: float = 0.0
    speak_gate: str = "listen"
    director_cache: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "outline": self.outline.snapshot(),
            "rhythm": self.rhythm.snapshot(),
            "poll_cursors": {
                key: cursor.snapshot() for key, cursor in self.poll_cursors.items()
            },
            "delivery_plan": (
                self.delivery_plan.snapshot() if self.delivery_plan is not None else None
            ),
            "pending_delivery_plan": (
                self.pending_delivery_plan.snapshot()
                if self.pending_delivery_plan is not None
                else None
            ),
            "user_intent": self.user_intent,
            "user_intent_confidence": self.user_intent_confidence,
            "speak_gate": self.speak_gate,
            "director_cache": dict(self.director_cache),
            "notes": list(self.notes),
        }


class StateStore:
    """orchestrator 调度态存储：大纲、节奏、轮询游标、交付计划。"""

    def __init__(self) -> None:
        self._states: dict[str, SessionSchedulingState] = {}
        self._lock = threading.Lock()

    def session(self, session_id: str) -> SessionSchedulingState:
        sid = session_id.strip()
        with self._lock:
            if sid not in self._states:
                self._states[sid] = SessionSchedulingState(session_id=sid)
            return self._states[sid]

    def poll_cursor(self, session_id: str, trigger: str) -> PollCursor:
        state = self.session(session_id)
        key = trigger.strip()
        if key not in state.poll_cursors:
            from ..core.poll import PollCursor as _PollCursor

            state.poll_cursors[key] = _PollCursor(
                session_id=session_id.strip(),
                trigger=key,  # type: ignore[arg-type]
            )
        return state.poll_cursors[key]

    def set_delivery_plan(
        self,
        session_id: str,
        plan: DeliveryPlan | None,
        *,
        pending: bool = False,
    ) -> None:
        state = self.session(session_id)
        if pending:
            state.pending_delivery_plan = plan
        else:
            state.delivery_plan = plan

    def take_pending_delivery_plan(self, session_id: str) -> DeliveryPlan | None:
        state = self.session(session_id)
        plan = state.pending_delivery_plan
        state.pending_delivery_plan = None
        return plan

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._lock:
            self._states.pop(sid, None)

    def snapshot(self, session_id: str) -> dict[str, Any]:
        return self.session(session_id).snapshot()
