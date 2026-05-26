from __future__ import annotations

from agent.soul.presence.state import PresenceEvent
from agent.soul.presence.service import PresenceService
from agent.soul.presence.transition import (
    PresenceTrigger,
    PresenceTriggerKind,
    PresenceTransitionRouter,
    TransitionHandler,
    TransitionNotes,
)


class _StaticHandler:
    def apply(self, *, session_id, state, interaction, payload) -> TransitionNotes:
        _ = session_id
        _ = interaction
        _ = payload
        state.affect.narrative = "injected static"
        return TransitionNotes(applied=True, notes=["static handler"])


def test_presence_trigger_registry_injection(tmp_path):
    router = PresenceTransitionRouter()
    router.register(PresenceTriggerKind.inject, _StaticHandler())
    svc = PresenceService(life_dir=str(tmp_path), transition_router=router)
    trigger = PresenceTrigger(
        kind=PresenceTriggerKind.inject,
        session_id="tao",
        payload={},
    )

    result = svc.interface.trigger(trigger)
    assert result.applied is True
    assert "injected static" in svc.snapshot("tao").state.affect.narrative


def test_presence_trigger_boundary_delegates_to_ingest():
    svc = PresenceService()
    event = PresenceEvent.user_text("tao")
    trigger = PresenceTrigger.boundary(event)

    trigger_result = svc.interface.trigger(trigger)
    ingest_result = svc.interface.boundary(event)

    assert trigger_result.boundary is True
    assert trigger_result.after == ingest_result.after
    assert trigger_result.outcome.boundary is not None
