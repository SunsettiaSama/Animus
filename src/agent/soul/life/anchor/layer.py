from __future__ import annotations

from ..experience.builder import ExperienceBuilder
from ..experience.unit import ExperienceUnit
from ..orchestrator import ExperienceOrchestrator
from .chronicle import AnchorChronicleStore
from .inbound import InboundRecorder, SchedulerDigestRecorder
from .outbound import InMemoryProactiveOutbound, ProactiveOutboundIntent, ProactiveOutboundPort


class AnchorLayer:
    """现实锚点层：入站（用户输入）与出站（主动会话）两链路。"""

    def __init__(
        self,
        life_dir: str,
        orchestrator: ExperienceOrchestrator,
        builder: ExperienceBuilder,
        chronicle: AnchorChronicleStore | None = None,
        outbound: ProactiveOutboundPort | None = None,
    ) -> None:
        self._chronicle = chronicle or AnchorChronicleStore(life_dir)
        self._orchestrator = orchestrator
        self._builder = builder
        self._inbound = InboundRecorder(orchestrator, self._chronicle)
        self._digest = SchedulerDigestRecorder(self._chronicle)
        self._outbound = outbound or InMemoryProactiveOutbound()

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
        return self._inbound.record_turn(
            session_id=session_id,
            user_text=user_text,
            agent_reply=agent_reply,
            salience=salience,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=activated_memory_ids,
            proactive_intent_id=proactive_intent_id,
        )

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
        return self._outbound.submit(intent)

    def pending_proactive_outbounds(self) -> list[ProactiveOutboundIntent]:
        return self._outbound.list_pending()


RealityAnchorLayer = AnchorLayer
