from __future__ import annotations

from datetime import datetime, timezone

from ..experience.builder import ExperienceBuilder
from ..experience.unit import ExperienceUnit
from ..orchestrator import ExperienceOrchestrator
from .chronicle import AnchorChronicleStore
from .inbound import InboundRecorder, SchedulerDigestRecorder
from .internalization import AnchorInternalizer
from .outbound import InMemoryProactiveOutbound, ProactiveOutboundIntent, ProactiveOutboundPort


class AnchorLayer:
    """现实锚点层：入站 / 出站经内化层闭合为会话级体验。"""

    def __init__(
        self,
        life_dir: str,
        orchestrator: ExperienceOrchestrator,
        builder: ExperienceBuilder,
        chronicle: AnchorChronicleStore | None = None,
        outbound: ProactiveOutboundPort | None = None,
        *,
        turn_promote_threshold: float = 0.65,
        interaction_idle_close_sec: float = 1800.0,
    ) -> None:
        self._chronicle = chronicle or AnchorChronicleStore(life_dir)
        self._orchestrator = orchestrator
        self._builder = builder
        self._inbound = InboundRecorder(orchestrator, self._chronicle)
        self._digest = SchedulerDigestRecorder(self._chronicle)
        self._outbound = outbound or InMemoryProactiveOutbound()
        self._internalizer = AnchorInternalizer(
            self._inbound,
            orchestrator,
            self._chronicle,
            turn_promote_threshold=turn_promote_threshold,
            idle_close_sec=interaction_idle_close_sec,
        )

    @property
    def chronicle(self) -> AnchorChronicleStore:
        return self._chronicle

    @property
    def builder(self) -> ExperienceBuilder:
        return self._builder

    @property
    def orchestrator(self) -> ExperienceOrchestrator:
        return self._orchestrator

    @property
    def inbound(self) -> InboundRecorder:
        return self._inbound

    @property
    def internalizer(self) -> AnchorInternalizer:
        return self._internalizer

    @property
    def outbound(self) -> ProactiveOutboundPort:
        return self._outbound

    @property
    def turn_index(self) -> int:
        return self._inbound.turn_index

    def record_user_turn(
        self,
        session_id: str,
        user_text: str,
        agent_reply: str,
        salience: float = 0.3,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
    ) -> ExperienceUnit:
        if proactive_intent_id:
            self._outbound.acknowledge(proactive_intent_id)
        return self._internalizer.append_inbound_turn(
            session_id,
            user_text,
            agent_reply,
            salience=salience,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=activated_memory_ids,
            proactive_intent_id=proactive_intent_id,
        )

    def close_interaction(self, session_id: str) -> ExperienceUnit | None:
        return self._internalizer.close_interaction(session_id)

    def close_idle_interactions(
        self,
        *,
        now: datetime | None = None,
    ) -> list[ExperienceUnit]:
        return self._internalizer.close_idle_sessions(now=now)

    def record_scheduler_digest(self, tasks_text: str) -> None:
        self._digest.record(tasks_text)

    def submit_proactive_outbound(
        self,
        message: str,
        *,
        reason: str = "",
        session_id: str = "tao",
        salience: float = 0.4,
    ) -> str:
        intent = ProactiveOutboundIntent(
            message=message,
            reason=reason,
            session_id=session_id,
            salience=salience,
        )
        intent_id = self._outbound.submit(intent)
        self._internalizer.open_outbound(
            session_id,
            message,
            reason=reason,
            proactive_intent_id=intent_id,
            salience=salience,
        )
        return intent_id

    def pending_proactive_outbounds(self) -> list[ProactiveOutboundIntent]:
        return self._outbound.list_pending()


RealityAnchorLayer = AnchorLayer
