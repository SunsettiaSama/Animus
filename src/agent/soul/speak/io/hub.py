from __future__ import annotations

from .inbound.hub import SpeakInboundHub
from .outbound.hub import SpeakOutboundHub


class SpeakIOHub:
    """Speak 出入站总线：``SpeakService`` 经 ``self.io`` 访问入站/出站，避免在 service 内散落 gateway。"""

    def __init__(self, inbound: SpeakInboundHub, outbound: SpeakOutboundHub) -> None:
        self.inbound = inbound
        self.outbound = outbound
