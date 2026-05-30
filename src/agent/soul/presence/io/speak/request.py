from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.state.dynamic.expectation.package import ShareFoldedPackage
from agent.soul.presence.transition.expectation import Expectation


@dataclass(frozen=True)
class ProactiveInitiateInbound:
    """Presence → Speak：主动发起回话请求。"""

    channel_id: str
    message: str
    base_session_id: str = ""
    session_id: str = ""
    reason: str = ""
    source: str = "presence:proactive"
    wait_reply: bool = True
    append: bool = False
    expectation: Expectation = Expectation.required
    package: ShareFoldedPackage | None = None
    presence_narrative: str = ""
    impulse_level: float = 0.0
    share_desire: ShareDesire = ShareDesire.mild
    proactive_intent_id: str = ""
    agent_display_name: str = ""

    @staticmethod
    def from_speak_request(
        request,
        *,
        channel_id: str = "",
        agent_display_name: str = "",
    ) -> ProactiveInitiateInbound:
        append = (
            request.source == "expectation_scan:append"
            or not request.wait_reply
        )
        if append:
            sid = request.session_id.strip()
        else:
            sid = f"proactive-{uuid.uuid4()}"
        pkg = request.package
        return ProactiveInitiateInbound(
            channel_id=channel_id.strip() or request.session_id.strip(),
            base_session_id=request.session_id.strip(),
            session_id=sid,
            message=(request.reason.strip() or pkg.summary.strip()),
            reason=request.reason,
            source=request.source or "presence:proactive",
            wait_reply=request.wait_reply,
            append=append,
            expectation=request.expectation,
            package=pkg,
            presence_narrative=request.presence_narrative,
            impulse_level=request.impulse_level,
            share_desire=request.share_desire,
            agent_display_name=agent_display_name,
        )


@dataclass
class ProactiveInitiateAck:
    ok: bool
    session_id: str = ""
    channel_id: str = ""
    message: str = ""
    proactive_intent_id: str = ""
    agent_initiated: bool = False
    append: bool = False
    blocked: bool = False
    reason: str = ""
    ui: dict[str, Any] = field(default_factory=dict)
