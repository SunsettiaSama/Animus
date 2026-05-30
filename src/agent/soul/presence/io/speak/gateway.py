from __future__ import annotations

from typing import TYPE_CHECKING

from .request import ProactiveInitiateAck, ProactiveInitiateInbound

if TYPE_CHECKING:
    from agent.soul.speak.io.inbound.presence.bridge import SpeakPresenceInboundBridge


class PresenceSpeakIO:
    """Presence 出站 → Speak 入站（主动回话）。"""

    def __init__(self, inbound: SpeakPresenceInboundBridge) -> None:
        self._inbound = inbound

    def initiate(self, inbound: ProactiveInitiateInbound) -> ProactiveInitiateAck:
        return self._inbound.initiate_proactive(inbound)

    def initiate_from_speak_request(
        self,
        request,
        *,
        channel_id: str = "",
        agent_display_name: str = "",
    ) -> ProactiveInitiateAck:
        body = ProactiveInitiateInbound.from_speak_request(
            request,
            channel_id=channel_id,
            agent_display_name=agent_display_name,
        )
        return self.initiate(body)
