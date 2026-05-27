from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.soul.presence.state.dynamic.kind import Expectation
from agent.soul.request import SoulDomain, SoulRequest

from ..actions import SpeakAction
from .request import SpeakRequest

if TYPE_CHECKING:
    from agent.soul.service import SoulService

_BLOCKED_PROACTIVE = frozenset({
    Expectation.required.value,
    Expectation.deferred.value,
    Expectation.clarify.value,
})


class SpeakPresenceOutbound:
    """Presence 主动出站：expectation 门控 + SpeakService 记账。"""

    def __init__(self, soul: SoulService) -> None:
        self._soul = soul

    @property
    def _speak(self):
        return self._soul._ensure_speak_service()

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
            source=request.source or "presence:speak_request",
            expectation=expectation,
            package=request.package.to_dict(),
            presence_narrative=request.presence_narrative,
        )

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

        share_line = str((package or {}).get("summary", ""))
        narration_parts = [part for part in (presence_narrative.strip(), share_line) if part]
        narration = "\n".join(narration_parts)
        delivered = self._speak.deliver_agent_message(
            session_id=session_id,
            message=text,
            user_text="",
            narration=narration,
            proactive_intent_id=proactive_intent_id,
            record=True,
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
            "turn": delivered,
        }
