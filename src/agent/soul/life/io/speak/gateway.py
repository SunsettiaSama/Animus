from __future__ import annotations

from typing import TYPE_CHECKING

from .request import (
    DialogueSessionCloseAck,
    DialogueSessionCloseInbound,
    DialogueSessionOpenAck,
    DialogueSessionOpenInbound,
    DialogueTurnInbound,
    ProactiveOutboundInbound,
    TouchDialogueInbound,
)

if TYPE_CHECKING:
    from agent.soul.life.experience.hub import LifeExperienceStack


class LifeSpeakIO:
    """Life 侧 Speak 入站总线（Soul 在 ``_ensure_experience_pipeline`` 后构造并持有）。"""

    def __init__(self, stack: LifeExperienceStack) -> None:
        self._stack = stack

    @property
    def stack(self) -> LifeExperienceStack:
        return self._stack

    def submit_dialogue_turn(self, inbound: DialogueTurnInbound) -> None:
        self._stack.record_dialogue_turn(
            session_id=inbound.session_id,
            user_text=inbound.user_text,
            agent_text=inbound.agent_text,
            salience=inbound.salience,
            salience_note=inbound.salience_note,
            emotion_label=inbound.emotion_label,
            valence_delta=inbound.valence_delta,
            arousal_delta=inbound.arousal_delta,
            activated_memory_ids=list(inbound.activated_memory_ids),
            proactive_intent_id=inbound.proactive_intent_id,
        )

    def touch_dialogue(self, inbound: TouchDialogueInbound) -> None:
        state = self._stack.dialogue.state(inbound.session_id)
        if state is not None:
            state.touch()

    def open_dialogue_session(
        self,
        inbound: DialogueSessionOpenInbound,
    ) -> DialogueSessionOpenAck:
        state = self._stack.dialogue.open_session(inbound.session_id)
        return DialogueSessionOpenAck(
            ok=True,
            session_id=inbound.session_id,
            trigger=inbound.trigger,
            turn_count=len(state.session.turns),
        )

    def open_proactive_outbound(self, inbound: ProactiveOutboundInbound) -> dict[str, object]:
        self._stack.dialogue.open_outbound(
            inbound.session_id,
            inbound.message,
            proactive_intent_id=inbound.proactive_intent_id,
        )
        return {
            "ok": True,
            "session_id": inbound.session_id,
            "message": inbound.message,
            "proactive_intent_id": inbound.proactive_intent_id,
        }

    def close_dialogue_session(
        self,
        inbound: DialogueSessionCloseInbound,
    ) -> DialogueSessionCloseAck:
        unit = self._stack.close_dialogue(inbound.session_id)
        if unit is None:
            return DialogueSessionCloseAck(
                ok=True,
                session_id=inbound.session_id,
                ingested=False,
            )
        return DialogueSessionCloseAck(
            ok=True,
            session_id=inbound.session_id,
            ingested=True,
            source=unit.source,
            turn_index=unit.situation.turn_index,
            experience_id=unit.id,
        )
