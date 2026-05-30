from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.soul.presence.state.dynamic.kind import Expectation

from .request import SpeakRequest

if TYPE_CHECKING:
    from agent.soul.service import SoulService


class SpeakPresenceOutbound:
    """Presence 主动出站：委托 Soul → presence.io.speak → speak.io.inbound.presence。"""

    def __init__(self, soul: SoulService) -> None:
        self._soul = soul

    def handle(self, request: SpeakRequest) -> dict[str, Any]:
        return self._soul._handle_presence_speak_trigger(request.session_id, request)

    def deliver_agent_message(
        self,
        *,
        session_id: str,
        message: str,
        wait_reply: bool = True,
        append: bool = False,
        source: str = "speak:deliver",
        expectation: Expectation | None = None,
        package: dict[str, Any] | None = None,
        presence_narrative: str = "",
    ) -> dict[str, Any]:
        from agent.soul.presence.io.speak.request import ProactiveInitiateInbound

        pkg_obj = None
        exp = expectation
        if exp is None:
            exp = Expectation.optional if append or not wait_reply else Expectation.required
        self._soul._ensure_presence_speak_io()
        ack = self._soul.presence.io.speak.initiate(
            ProactiveInitiateInbound(
                channel_id=session_id,
                base_session_id=session_id,
                session_id=session_id if append else "",
                message=message,
                source=source,
                wait_reply=wait_reply,
                append=append,
                expectation=exp,
                package=pkg_obj,
                presence_narrative=presence_narrative,
            ),
        )
        return {
            "ok": ack.ok,
            "session_id": ack.session_id,
            "message": ack.message,
            "wait_reply": wait_reply,
            "append": append,
            "source": source,
            "expectation": exp.value,
            "turn": {"exchange_id": ack.reason},
        }
