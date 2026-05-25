from __future__ import annotations

from .chronicle import AnchorChronicleEntry, AnchorChronicleKind, AnchorChronicleStore
from .inbound import SchedulerDigestRecorder
from .outbound import InMemoryProactiveOutbound, ProactiveOutboundIntent, ProactiveOutboundPort


class AnchorLayer:
    """现实锚点层：调度摘要与出站意图（对话体验由 presence/experience 维护）。"""

    def __init__(
        self,
        life_dir: str,
        chronicle: AnchorChronicleStore | None = None,
        outbound: ProactiveOutboundPort | None = None,
    ) -> None:
        self._chronicle = chronicle or AnchorChronicleStore(life_dir)
        self._digest = SchedulerDigestRecorder(self._chronicle)
        self._outbound = outbound or InMemoryProactiveOutbound()

    @property
    def chronicle(self) -> AnchorChronicleStore:
        return self._chronicle

    @property
    def outbound(self) -> ProactiveOutboundPort:
        return self._outbound

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
        self._chronicle.append(AnchorChronicleEntry(
            kind=AnchorChronicleKind.interaction_open,
            summary=f"出站：{message[:80]}",
            session_id=session_id,
            salience=salience,
            experience_id=intent_id,
        ))
        return intent_id

    def pending_proactive_outbounds(self) -> list[ProactiveOutboundIntent]:
        return self._outbound.list_pending()

    def acknowledge_proactive_outbound(self, intent_id: str) -> None:
        self._outbound.acknowledge(intent_id)


RealityAnchorLayer = AnchorLayer
