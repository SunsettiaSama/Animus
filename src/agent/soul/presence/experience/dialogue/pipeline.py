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
        presence: PresenceService,
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
        from agent.soul.presence.fsm.events import PresenceEvent

        item = self._ensure_state(session_id)

        presence.ingest(PresenceEvent.user_text(session_id))
        presence.observe_dialogue_turn(
            session_id,
            user_text=user_text,
            agent_text=agent_text,
        )
        presence.ingest(PresenceEvent.agent_utterance(session_id, final=True))

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
        self._sync_working_memory(presence, session_id, item, now=now)

    def close_dialogue(
        self,
        presence: PresenceService,
        session_id: str,
    ) -> ExperienceUnit | None:
        item = self._states.pop(session_id, None)
        if item is None or not item.session.turns:
            return None

        item.reset_working_memory()
        self._sync_working_memory(presence, session_id, item)

        experience = presence.finalize_dialogue_experience(session_id)
        if experience is None:
            return None

        unit = unit_from_dialogue_session(item.session, experience)
        self._orchestrator.ingest(unit)
        return unit

    def _sync_working_memory(
        self,
        presence: PresenceService,
        session_id: str,
        item: DialogueState,
        *,
        now: datetime | None = None,
    ) -> None:
        session = presence._session(session_id)
        session.state.cognition.working_memory = item.working_memory_text(now=now)
