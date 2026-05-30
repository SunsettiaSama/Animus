from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.compose.composer import SpeakPromptComposer
from agent.soul.speak.compose.context.distiller import SpeakContextDistiller
from agent.soul.speak.io.inbound.compose import SpeakStatusInjected


@dataclass
class _Snap:
    state: object = None


class _Presence:
    def snapshot(self, session_id: str) -> _Snap:
        return _Snap(state=None)


class _Persona:
    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict:
        return {}


def test_refresh_status_for_turn_keeps_presence_only():
    distiller = SpeakContextDistiller(chunk_size=4)
    state = distiller._session("s1")
    with state.lock:
        state.distilled.append("荧与莉奈娅谈到船与探险队。")

    composer = SpeakPromptComposer(
        _Persona(),
        _Presence(),
        context_distiller=distiller,
    )
    refreshed = composer.refresh_status_for_turn(
        "s1",
        SpeakStatusInjected(similar_memories="【涌现记忆·长期】\n- old"),
    )
    assert refreshed.dialogue_compressed == ""
    assert refreshed.similar_memories.startswith("【涌现记忆·长期】")
