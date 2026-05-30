from __future__ import annotations

from .life import SpeakLifeOutboundBridge
from .stream_hub import SpeakOutboundStreamHub


class SpeakOutboundHub:
    """Speak 出站总线：流式推送 + Life 体验注入。"""

    def __init__(
        self,
        stream: SpeakOutboundStreamHub,
        *,
        life: SpeakLifeOutboundBridge | None = None,
    ) -> None:
        self.stream = stream
        self.life = life

    def bind_stream_port(self, port) -> None:
        self.stream.bind_port(port)
