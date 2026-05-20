from __future__ import annotations

from dataclasses import dataclass, field

from ..fsm.events import DriveEvent
from ..fsm.state import DriveContext, DriveState
from ..transition import TransitionResult, apply_transition
from .evolution import drive_event_from_capture
from .events import BOUNDARY_KINDS, EVOLUTION_KINDS, CaptureEvent, CaptureKind
from .impulse import apply_evolution_impulse


@dataclass
class CaptureResult:
    session_id: str
    event: CaptureEvent
    before: DriveState
    after: DriveState
    notes: list[str] = field(default_factory=list)
    boundary: bool = False


class DriveCapture:
    """事件捕获：顶层注入走 transition；内部演化累积冲动。"""

    def ingest(
        self,
        state: DriveState,
        event: CaptureEvent,
        context: DriveContext,
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

        drive_event = drive_event_from_capture(event)
        transition: TransitionResult = apply_transition(state, drive_event, context)
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
        state: DriveState,
        event: DriveEvent,
        context: DriveContext,
    ) -> CaptureResult:
        from .evolution import capture_event_from_drive

        return self.ingest(state, capture_event_from_drive(event), context)
