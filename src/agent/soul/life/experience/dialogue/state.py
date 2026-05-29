from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..anchor_codec import InteractionDirection
from .session import DialogueSession, DialogueTurn
from .working_memory import DialogueWorkingMemory, _utc_now


@dataclass
class DialogueState:
    """对话模态当下态。

    - ``session.turns``：全量 verbatim 交互账本（memory 燃料，不截断）
    - ``working_memory``：当下 FSM 窗口（超窗/超量直接抛弃，不蒸馏）
    """

    session: DialogueSession
    working_memory: DialogueWorkingMemory = field(default_factory=DialogueWorkingMemory)
    last_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def open(cls, session_id: str) -> DialogueState:
        return cls(
            session=DialogueSession(session_id=session_id),
            working_memory=DialogueWorkingMemory(),
        )

    @property
    def session_id(self) -> str:
        return self.session.session_id

    def touch(self, *, now: datetime | None = None) -> None:
        self.last_at = _utc_now(now)

    def record_turn(
        self,
        *,
        user_text: str,
        agent_text: str,
        salience: float = 0.3,
        salience_note: str = "",
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
        now: datetime | None = None,
    ) -> DialogueTurn:
        ts = _utc_now(now)
        self.touch(now=ts)
        if proactive_intent_id:
            self.session.proactive_intent_id = proactive_intent_id
            self.session.direction = InteractionDirection.outbound

        if user_text.strip() or agent_text.strip():
            self.working_memory.append_turn(user_text, agent_text, now=ts)

        turn = DialogueTurn(
            user_text=user_text,
            agent_text=agent_text,
            salience=salience,
            salience_note=salience_note.strip(),
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=list(activated_memory_ids or []),
            proactive_intent_id=proactive_intent_id,
        )
        self.session.turns.append(turn)
        return turn

    def working_memory_text(self, *, now: datetime | None = None) -> str:
        return self.working_memory.render(now=now)

    def reset_working_memory(self) -> None:
        self.working_memory.chunks.clear()
