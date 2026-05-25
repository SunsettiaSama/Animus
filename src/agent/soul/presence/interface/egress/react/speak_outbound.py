from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.soul.handlers.api.actions import SpeakAction
from agent.soul.presence.interface.egress.request import SpeakRequest
from agent.soul.presence.transition.expectation import Expectation
from agent.soul.request import SoulDomain, SoulRequest

if TYPE_CHECKING:
    from agent.soul.service import SoulService

_BLOCKED_PROACTIVE = frozenset({
    Expectation.required.value,
    Expectation.deferred.value,
    Expectation.clarify.value,
})


class PresenceReactOutbound:
    """expectation/interface → speak 出站：记账 + 同步 interaction 期待。"""

    def __init__(self, soul: SoulService) -> None:
        self._soul = soul

    def handle(self, request: SpeakRequest) -> dict[str, Any]:
        append = (
            request.source == "expectation_scan:append"
            or not request.wait_reply
        )
        message = request.reason.strip()
        if not message and request.package.summary.strip():
            message = request.package.summary.strip()
        if not message:
            return {"ok": False, "reason": "empty speak message", "source": request.source}

        expectation = request.expectation
        if append:
            expectation = Expectation.optional

        return self.deliver_agent_message(
            session_id=request.session_id,
            message=message,
            wait_reply=request.wait_reply,
            append=append,
            source=request.source or "interface:speak_request",
            expectation=expectation,
            package=request.package.to_dict(),
        )

    def deliver_agent_message(
        self,
        *,
        session_id: str,
        message: str,
        wait_reply: bool = True,
        append: bool = False,
        source: str = "react:speak_to_user",
        expectation: Expectation | None = None,
        package: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = message.strip()
        if not text:
            raise ValueError("speak message 不能为空")

        snap = self._soul.presence.snapshot(session_id)
        if not append and snap.expectation.value in _BLOCKED_PROACTIVE:
            return {
                "ok": False,
                "blocked": True,
                "reason": "interaction expectation blocks proactive speak",
                "expectation": snap.expectation.value,
            }

        self._soul.start_dialogue_session(session_id)

        proactive_intent_id = ""
        if not append:
            outbound = self._soul.dispatch(SoulRequest(
                domain=SoulDomain.speak,
                action=SpeakAction.OPEN_OUTBOUND,
                payload={
                    "session_id": session_id,
                    "message": text,
                    "proactive_intent_id": proactive_intent_id,
                },
            ))
            proactive_intent_id = str(outbound.get("proactive_intent_id", ""))

        turn = self._soul.record_dialogue_turn(
            "",
            text,
            session_id=session_id,
            proactive_intent_id=proactive_intent_id,
            narration=str((package or {}).get("summary", "")),
        )

        exp = expectation
        if exp is None:
            exp = Expectation.optional if append or not wait_reply else Expectation.required
        self._soul.presence.bind(session_id, expectation=exp)

        return {
            "ok": True,
            "session_id": session_id,
            "message": text,
            "wait_reply": wait_reply,
            "append": append,
            "source": source,
            "expectation": exp.value,
            "turn": turn,
        }
