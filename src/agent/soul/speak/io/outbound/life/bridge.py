from __future__ import annotations

from agent.soul.life.io.speak import (
    DialogueTurnInbound,
    LifeSpeakIO,
    TouchDialogueInbound,
)

from ....session import (
    SpeakTurnChunk,
    feeling_self_narration,
    resolve_feeling,
    resolve_subjective,
)
from ..unit import SpeakAnswer
from ...inbound.unit import SpeakExchange, SpeakQuestion


class SpeakLifeOutboundBridge:
    """Speak → Life 出站：轮次记账与会话 touch（经 ``LifeSpeakIO``）。"""

    def __init__(self, life_io: LifeSpeakIO) -> None:
        self._life = life_io

    @property
    def life_io(self) -> LifeSpeakIO:
        return self._life

    def emit_dialogue_turn(self, chunk: SpeakTurnChunk) -> None:
        resolved = resolve_feeling(chunk)
        self._life.submit_dialogue_turn(
            DialogueTurnInbound(
                session_id=chunk.session_id,
                user_text=chunk.user_text,
                agent_text=chunk.agent_text,
                salience=resolved.salience,
                salience_note=feeling_self_narration(chunk.feeling),
                emotion_label=resolved.emotion_label,
                valence_delta=resolved.valence_delta,
                arousal_delta=resolved.arousal_delta,
                activated_memory_ids=tuple(chunk.activated_memory_ids),
                proactive_intent_id=chunk.proactive_intent_id,
            ),
        )

    def touch_dialogue(self, session_id: str) -> None:
        sid = session_id.strip()
        if not sid:
            return
        self._life.touch_dialogue(TouchDialogueInbound(session_id=sid))

    def record_turn_exchange(self, chunk: SpeakTurnChunk) -> SpeakExchange:
        """写入 Life 并返回 Speak 侧 ``SpeakExchange``（供 session 记账链使用）。"""
        self.emit_dialogue_turn(chunk)
        subj = resolve_subjective(chunk)
        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
            subjective=subj,
            feeling=chunk.feeling,
        )
