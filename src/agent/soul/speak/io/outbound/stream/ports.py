from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .events import SpeakStreamEvent


class SpeakStreamPort(Protocol):
    """流式出站订阅口：外界实现此协议以接收 SpeakStreamEvent。"""

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None: ...
