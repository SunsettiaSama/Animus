from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent.soul.request import SoulDomain, SoulRequest

from ..actions import SpeakAction
from .delivery import SpeakPresenceOutbound
from .request import SpeakRequest
from .stream.ports import SpeakStreamPort

if TYPE_CHECKING:
    from agent.soul.service import SoulService

PresenceOutboundHandler = Callable[[SpeakRequest], Any]


class SpeakOutboundRouter:
    """Speak 出站路由：stream / presence / text 三路统一挂载。"""

    def __init__(self, soul: SoulService) -> None:
        self._soul = soul
        self._presence = SpeakPresenceOutbound(soul)
        self._after_presence_handlers: list[PresenceOutboundHandler] = []

    @property
    def presence(self) -> SpeakPresenceOutbound:
        return self._presence

    def bind_stream(self, port: SpeakStreamPort | None) -> None:
        """挂载流式出站 port（run_turn / generate_stream 事件经此抛出）。"""
        self._soul._ensure_speak_service().set_stream_port(port)

    @property
    def stream_port(self) -> SpeakStreamPort | None:
        return self._soul._ensure_speak_service().outbound_stream.port

    def register_after_presence(self, handler: PresenceOutboundHandler) -> None:
        """presence 主动出站完成后触发的回调（审计 / UI 等）。"""
        self._after_presence_handlers.append(handler)

    def emit_presence(self, request: SpeakRequest) -> dict[str, Any]:
        """Presence → Speak 主动出站。"""
        result = self._presence.handle(request)
        for handler in self._after_presence_handlers:
            handler(request)
        return result

    def deliver_agent_message(
        self,
        *,
        session_id: str,
        message: str,
        wait_reply: bool = True,
        append: bool = False,
        source: str = "speak:deliver",
        expectation=None,
        package: dict[str, Any] | None = None,
        presence_narrative: str = "",
    ) -> dict[str, Any]:
        return self._presence.deliver_agent_message(
            session_id=session_id,
            message=message,
            wait_reply=wait_reply,
            append=append,
            source=source,
            expectation=expectation,
            package=package,
            presence_narrative=presence_narrative,
        )

    def deliver_text(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> dict[str, Any]:
        """文本出站（DELIVER action）。"""
        return self._soul.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=SpeakAction.DELIVER,
            payload={
                "session_id": session_id,
                "text": text,
                "final": final,
            },
        ))
