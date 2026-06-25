from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.pipelines.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.pipelines.request_driven.orchestrator.guidance.context import SpeakContextDistiller
from agent.soul.speak.pipelines.request_driven.orchestrator.orchestrator import SpeakOrchestrator
from agent.soul.speak.pipelines.request_driven.orchestrator.persona import SpeakPersonaLayer
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill


@dataclass
class _Snap:
    state: object = None


class _Presence:
    def snapshot(self, session_id: str) -> _Snap:
        return _Snap(state=None)


class _Persona:
    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict:
        return persona_snapshot_with_distill()


def test_refresh_persona_for_turn_does_not_carry_memory_on_persona():
    distiller = SpeakContextDistiller(chunk_size=4)
    state = distiller._session("s1")
    with state.lock:
        state.distilled.append("recent dialogue")

    orchestrator = SpeakOrchestrator(
        _Persona(),
        _Presence(),
        context_distiller=distiller,
    )
    orchestrator.prepare("s1")
    refreshed = orchestrator.refresh_persona_for_turn(
        "s1",
        SpeakPersonaLayer(dialogue_compressed="stale compressed"),
    )
    assert refreshed.dialogue_compressed == ""
    assert refreshed.self_narrative.strip()
