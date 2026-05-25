from __future__ import annotations

from collections.abc import Callable

from .chunk import SpeakTurnChunk, resolve_feeling, resolve_subjective
from .unit import SpeakAnswer, SpeakExchange, SpeakQuestion

RecordDialogueFn = Callable[..., None]


class SpeakDialogueBridge:
    """一次调用：speak 记账 → presence/experience 连续体验。"""

    def __init__(
        self,
        *,
        on_dialogue_turn: RecordDialogueFn | None = None,
    ) -> None:
        self._on_dialogue_turn = on_dialogue_turn

    def record_turn(self, chunk: SpeakTurnChunk) -> SpeakExchange:
        subj = resolve_subjective(chunk)
        resolved = resolve_feeling(chunk)

        if self._on_dialogue_turn is not None:
            self._on_dialogue_turn(
                session_id=chunk.session_id,
                user_text=chunk.user_text,
                agent_text=chunk.agent_text,
                salience=resolved.salience,
                emotion_label=resolved.emotion_label,
                valence_delta=resolved.valence_delta,
                arousal_delta=resolved.arousal_delta,
                activated_memory_ids=chunk.activated_memory_ids,
                proactive_intent_id=chunk.proactive_intent_id,
            )

        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
            subjective=subj,
            feeling=chunk.feeling,
        )
