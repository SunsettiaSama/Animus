from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ..orchestrator import ExperienceOrchestrator
from ..unit import ExperienceUnit
from ..anchor_codec import InteractionDirection
from .session import unit_from_dialogue_session
from .state import DialogueState

if TYPE_CHECKING:
    from agent.soul.presence.service import PresenceService


class DialogueExperiencePipeline:
    """对话体验：全量 session 燃料 + 工作记忆 verbatim 截断 → 闭合注入 memory。"""

    def __init__(
        self,
        orchestrator: ExperienceOrchestrator,
    ) -> None:
        self._orchestrator = orchestrator
        self._states: dict[str, DialogueState] = {}
        self._presence: PresenceService | None = None

    def bind_presence(self, presence: PresenceService) -> None:
        self._presence = presence

    def _resolve_presence(self, presence: PresenceService | None) -> PresenceService:
        if presence is not None:
            return presence
        if self._presence is None:
            raise RuntimeError("DialogueExperiencePipeline 未 bind_presence")
        return self._presence

    @property
    def orchestrator(self) -> ExperienceOrchestrator:
        return self._orchestrator

    def state(self, session_id: str) -> DialogueState | None:
        return self._states.get(session_id)

    def open_session(self, session_id: str) -> DialogueState:
        return self._ensure_state(session_id)

    def working_memory_text(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> str:
        item = self._states.get(session_id)
        if item is None:
            return ""
        return item.working_memory_text(now=now)

    def _ensure_state(self, session_id: str) -> DialogueState:
        item = self._states.get(session_id)
        if item is None:
            item = DialogueState.open(session_id)
            self._states[session_id] = item
        return item

    def open_outbound(
        self,
        session_id: str,
        message: str,
        *,
        proactive_intent_id: str = "",
    ) -> None:
        item = self._ensure_state(session_id)
        item.session.direction = InteractionDirection.outbound
        item.session.outbound_message = message.strip()
        item.session.proactive_intent_id = proactive_intent_id

    def record_dialogue_turn(
        self,
        presence: PresenceService | None,
        *,
        session_id: str,
        user_text: str,
        agent_text: str,
        salience: float = 0.3,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
        now: datetime | None = None,
    ) -> None:
        from agent.soul.presence.state import PresenceEvent

        item = self._ensure_state(session_id)
        pres = self._resolve_presence(presence)

        pres.ingest(PresenceEvent.user_text(session_id))
        pres.ingest(PresenceEvent.agent_utterance(session_id, final=True))

        item.record_turn(
            user_text=user_text,
            agent_text=agent_text,
            salience=salience,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=activated_memory_ids,
            proactive_intent_id=proactive_intent_id,
            now=now,
        )
        self._sync_working_memory(pres, session_id, item, now=now)

    def close_dialogue(
        self,
        presence: PresenceService | None,
        session_id: str,
    ) -> ExperienceUnit | None:
        from agent.soul.life.experience.dialogue.experience import build_dialogue_experience

        pres = self._resolve_presence(presence)
        item = self._states.pop(session_id, None)
        if item is None or not item.session.turns:
            return None

        item.reset_working_memory()
        self._sync_working_memory(pres, session_id, item)

        snap = pres.snapshot(session_id)
        if snap.state.is_empty():
            return None

        experience = build_dialogue_experience(snap.state, block_count=len(item.session.turns))
        unit = unit_from_dialogue_session(item.session, experience)
        self._orchestrator.ingest(unit)
        self._append_interaction_close_chronicle(unit, experience.narration)
        return unit

    def _append_interaction_close_chronicle(self, unit: ExperienceUnit, narration: str) -> None:
        chronicle = self._orchestrator.anchor_chronicle
        if chronicle is None:
            return
        from agent.soul.life.anchor.chronicle.entry import AnchorChronicleEntry, AnchorChronicleKind

        summary = (narration or unit.situation.perception or "")[:120]
        chronicle.append(AnchorChronicleEntry(
            kind=AnchorChronicleKind.interaction_close,
            summary=summary,
            session_id=unit.situation.session_id,
            turn_index=unit.situation.turn_index,
            emotion_label=unit.feeling.emotion_label,
            salience=unit.feeling.salience,
            experience_id=unit.id,
        ))

    def _sync_working_memory(
        self,
        presence: PresenceService,
        session_id: str,
        item: DialogueState,
        *,
        now: datetime | None = None,
    ) -> None:
        presence.set_working_memory(session_id, item.working_memory_text(now=now))
