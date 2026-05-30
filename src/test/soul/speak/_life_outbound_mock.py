from __future__ import annotations

from agent.soul.speak.io.outbound.unit import SpeakAnswer
from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
from agent.soul.speak.session import (
    SpeakTurnChunk,
    feeling_self_narration,
    resolve_feeling,
    resolve_subjective,
)


class RecordingSpeakLifeOutbound:
    """测试用：记录 emit_dialogue_turn 参数，不写入真实 Life。"""

    def __init__(self) -> None:
        self.recorded: list[dict] = []

    def touch_dialogue(self, session_id: str) -> None:
        _ = session_id

    def emit_dialogue_turn(self, chunk: SpeakTurnChunk) -> None:
        resolved = resolve_feeling(chunk)
        self.recorded.append({
            "session_id": chunk.session_id,
            "user_text": chunk.user_text,
            "agent_text": chunk.agent_text,
            "salience": resolved.salience,
            "salience_note": feeling_self_narration(chunk.feeling),
            "emotion_label": resolved.emotion_label,
            "valence_delta": resolved.valence_delta,
            "arousal_delta": resolved.arousal_delta,
            "activated_memory_ids": list(chunk.activated_memory_ids),
            "proactive_intent_id": chunk.proactive_intent_id,
        })

    def record_turn_exchange(self, chunk: SpeakTurnChunk) -> SpeakExchange:
        self.emit_dialogue_turn(chunk)
        subj = resolve_subjective(chunk)
        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
            subjective=subj,
            feeling=chunk.feeling,
        )
