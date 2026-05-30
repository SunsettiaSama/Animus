from __future__ import annotations

from ...session import SpeakTurnChunk
from ..outbound.life import SpeakLifeOutboundBridge


class SpeakDialogueBridge:
    """Speak 入站记账门面：委托 ``io.outbound.life`` 写入 Life 体验管线。"""

    def __init__(self, *, life: SpeakLifeOutboundBridge) -> None:
        self._life = life

    def record_turn(self, chunk: SpeakTurnChunk):
        return self._life.record_turn_exchange(chunk)
