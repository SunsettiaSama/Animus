from __future__ import annotations

from dataclasses import dataclass, field

from ..fsm.events import PresenceEvent
from ..fsm.state import PresenceContext, PresenceState
from ..transition import TransitionResult, apply_transition
from .evolution import presence_event_from_capture
from .events import BOUNDARY_KINDS, EVOLUTION_KINDS, CaptureEvent, CaptureKind
from .impulse import apply_evolution_impulse


@dataclass
class CaptureResult:
    session_id: str
    event: CaptureEvent
    before: PresenceState
    after: PresenceState
    notes: list[str] = field(default_factory=list)
    boundary: bool = False


class PresenceCapture:
    """事件捕获：顶层注入走 transition；内部演化累积冲动。"""

    def ingest(
        self,
        state: PresenceState,
        event: CaptureEvent,
        context: PresenceContext,
    ) -> CaptureResult:
        before = state.copy()
        notes: list[str] = []

        if event.kind in EVOLUTION_KINDS:
            notes.append(apply_evolution_impulse(state, event))
            return CaptureResult(
                session_id=event.session_id,
                event=event,
                before=before,
                after=state.copy(),
                notes=notes,
                boundary=False,
            )

        if event.kind not in BOUNDARY_KINDS:
            notes.append(f"capture: ignored {event.kind.value}")
            return CaptureResult(
                session_id=event.session_id,
                event=event,
                before=before,
                after=state.copy(),
                notes=notes,
            )

        presence_event = presence_event_from_capture(event)
        transition: TransitionResult = apply_transition(state, presence_event, context)
        notes.extend(transition.notes)

        return CaptureResult(
            session_id=event.session_id,
            event=event,
            before=before,
            after=state.copy(),
            notes=notes,
            boundary=True,
        )

    def inject_boundary(
        self,
        state: PresenceState,
        event: PresenceEvent,
        context: PresenceContext,
    ) -> CaptureResult:
        from .evolution import capture_event_from_presence

        return self.ingest(state, capture_event_from_presence(event), context)
