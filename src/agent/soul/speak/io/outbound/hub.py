from __future__ import annotations

from .bus import SpeakOutboundBus
from .life import SpeakLifeOutboundBridge
from .manager import OutboundMessageManager
from .notify.ports import SpeakNotifyPort
from .stream_hub import SpeakOutboundStreamHub


class SpeakOutboundHub:
    """Speak 出站总线：message manager + bus（缓冲+扇出）+ 流式推送 + Life。"""

    def __init__(
        self,
        stream: SpeakOutboundStreamHub,
        *,
        life: SpeakLifeOutboundBridge | None = None,
        bus: SpeakOutboundBus | None = None,
        manager: OutboundMessageManager | None = None,
    ) -> None:
        self.bus = bus or SpeakOutboundBus()
        self.manager = manager or OutboundMessageManager(self.bus)
        self.stream = stream
        self.life = life
        self.stream.channel.bind_bus(self.bus)

    def bind_stream_port(self, port) -> None:
        self.stream.bind_port(port)

    def attach_notify_port(self, port: SpeakNotifyPort) -> None:
        self.bus.attach_notify_port(port)

    def detach_notify_port(self, port: SpeakNotifyPort) -> None:
        self.bus.detach_notify_port(port)

    def publish_notify(self, item: dict) -> None:
        self.bus.publish_notify(item)

    def enqueue_proactive(self, payload: dict) -> dict:
        result = self.manager.accept_pending_payload(payload)
        return result.bus or {
            "ok": result.ok,
            "status": result.status,
            "delivered": result.status == "delivered",
            "payload": result.message.to_pending_payload(),
        }

    def bind_snapshot_sink(self, sink) -> None:
        self.bus.bind_snapshot_sink(sink)

    def resolve_create_ui(
        self,
        delivery_id: str,
        *,
        accepted: bool,
        channel_id: str = "",
        session_id: str = "",
    ) -> dict:
        return self.bus.resolve_create_ui(
            delivery_id,
            accepted=accepted,
            channel_id=channel_id,
            session_id=session_id,
        )

    def acknowledge_proactive(
        self,
        delivery_id: str,
        *,
        session_id: str = "",
        channel_id: str = "",
    ) -> bool:
        return self.bus.acknowledge_proactive(
            delivery_id,
            session_id=session_id,
            channel_id=channel_id,
        )
