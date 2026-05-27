from __future__ import annotations

from .events import SpeakStreamEvent

from .ports import SpeakStreamPort


class SpeakStreamChannel:
    """出站流式通道：绑定外界 port，将 parse/flush 产物向外抛出。"""

    def __init__(self) -> None:
        self._port: SpeakStreamPort | None = None

    def bind(self, port: SpeakStreamPort | None) -> None:
        self._port = port

    def begin_session(self, session_id: str) -> None:
        """标记本轮 outbound 流式通道就绪（compose → llm → push）。"""
        self._active_session_id = session_id

    @property
    def active_session_id(self) -> str | None:
        return getattr(self, "_active_session_id", None)

    @property
    def port(self) -> SpeakStreamPort | None:
        return self._port

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        if self._port is not None:
            self._port.emit(session_id, event)
