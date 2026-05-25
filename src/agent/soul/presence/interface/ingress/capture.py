from __future__ import annotations

from typing import TYPE_CHECKING

from ..shared.events import EVOLUTION_KINDS, CaptureEvent
from .evolution import apply_evolution_impulse
from ..egress.package import enqueue_share_event

if TYPE_CHECKING:
    from ...fsm import PresenceContext
    from ...service import PresenceIngestResult, PresenceService


def run_evolution_capture(
    service: PresenceService,
    event: CaptureEvent,
    *,
    context: PresenceContext | None = None,
) -> PresenceIngestResult:
    from ...service import PresenceIngestResult

    _ = context
    sid = event.session_id
    session = service._session(sid)
    before = service.snapshot(sid)
    notes: list[str] = []

    if event.kind not in EVOLUTION_KINDS:
        notes.append(f"interface: ignored {event.kind.value}")
        return PresenceIngestResult(
            before=before,
            after=before,
            event=event,
            notes=notes,
        )

    notes.append(
        apply_evolution_impulse(
            session.interaction,
            event,
            state=session.state,
        )
    )
    enqueue_share_event(session.state.expectation, event)

    speak_req = service._egress.evaluate(
        session_id=sid,
        interaction=session.interaction,
        expectation=session.state.expectation,
    )
    if speak_req is not None:
        session.interaction.discharge_impulse(speak_req.impulse_level)
        session.state.expectation.share_queue.drain()
        if service._on_speak_request is not None:
            service._on_speak_request(speak_req)

    service._sessions[sid] = session
    service._persist(sid)
    after = service.snapshot(sid)

    return PresenceIngestResult(
        before=before,
        after=after,
        event=event,
        notes=notes,
        speak_request=speak_req,
        boundary=False,
        buffered_share_count=len(session.state.expectation.share_queue),
    )
