from __future__ import annotations

from typing import TYPE_CHECKING

from .events import SpeakStreamEvent
from .ports import SpeakStreamPort

if TYPE_CHECKING:
    from agent.soul.speak.io.outbound.bus import SpeakOutboundBus


class SpeakStreamChannel:
    """出站流式通道：经 SpeakOutboundBus 缓冲后再扇出；无适配器时不丢决策结果。"""

    def __init__(self, bus: SpeakOutboundBus | None = None) -> None:
        self._bus = bus
        self._port: SpeakStreamPort | None = None

    def bind_bus(self, bus: SpeakOutboundBus) -> None:
        self._bus = bus

    def bind(self, port: SpeakStreamPort | None) -> None:
        self._port = port
        if self._bus is not None:
            self._bus.bind_stream_port(port)
        elif port is not None:
            # 无 bus 时退化为直连（测试/旧路径）
            pass

    def begin_session(self, session_id: str) -> None:
        self._active_session_id = session_id

    @property
    def active_session_id(self) -> str | None:
        return getattr(self, "_active_session_id", None)

    @property
    def port(self) -> SpeakStreamPort | None:
        if self._bus is not None:
            return self._bus.stream_port
        return self._port

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        if self._bus is not None:
            self._bus.publish_stream(session_id, event)
            return
        if self._port is not None:
            self._port.emit(session_id, event)
