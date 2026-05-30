from __future__ import annotations

from collections.abc import Callable

from agent.soul.life.io.speak import (
    DialogueSessionCloseInbound,
    DialogueSessionOpenInbound,
    LifeSpeakIO,
    ProactiveOutboundInbound,
)
from agent.soul.speak.session.lifecycle import SessionOpenTrigger

ResetContextFn = Callable[[str], None]


class SpeakLifeLifecycleBridge:
    """Speak 会话 rotate → Life dialogue 体验（``SessionLifecyclePort`` 实现）。"""

    def __init__(
        self,
        life_io: LifeSpeakIO,
        *,
        reset_context: ResetContextFn | None = None,
    ) -> None:
        self._life = life_io
        self._reset_context = reset_context or (lambda _sid: None)

    def close_dialogue_interaction(self, session_id: str) -> dict:
        self._reset_context(session_id)
        ack = self._life.close_dialogue_session(
            DialogueSessionCloseInbound(session_id=session_id),
        )
        result: dict = {
            "ok": ack.ok,
            "session_id": ack.session_id,
            "ingested": ack.ingested,
        }
        if ack.ingested:
            result["source"] = ack.source
            result["turn_index"] = ack.turn_index
            result["experience_id"] = ack.experience_id
        return result

    def start_dialogue_session(
        self,
        session_id: str,
        *,
        trigger: SessionOpenTrigger = "user_message",
    ) -> dict:
        ack = self._life.open_dialogue_session(
            DialogueSessionOpenInbound(session_id=session_id, trigger=trigger),
        )
        return {
            "ok": ack.ok,
            "session_id": ack.session_id,
            "trigger": ack.trigger,
            "turn_count": ack.turn_count,
        }

    def open_proactive_outbound(
        self,
        session_id: str,
        message: str,
        *,
        proactive_intent_id: str = "",
    ) -> dict:
        return self._life.open_proactive_outbound(
            ProactiveOutboundInbound(
                session_id=session_id,
                message=message,
                proactive_intent_id=proactive_intent_id,
            ),
        )
