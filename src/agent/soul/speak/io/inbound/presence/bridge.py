from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent.soul.presence.io.speak.request import ProactiveInitiateAck, ProactiveInitiateInbound
from agent.soul.presence.state import PresenceEvent
from agent.soul.presence.state.dynamic.kind import Expectation
from agent.soul.request import SoulDomain, SoulRequest
from agent.soul.speak.io.actions import SpeakAction
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent

if TYPE_CHECKING:
    from agent.soul.service import SoulService

AgentInitiatedNotify = Callable[[dict[str, Any]], None]

_BLOCKED_PROACTIVE = frozenset({
    Expectation.required.value,
    Expectation.deferred.value,
    Expectation.clarify.value,
})


class SpeakPresenceInboundBridge:
    """Speak 入站：接收 Presence 主动回话请求并向用户投递。"""

    def __init__(
        self,
        soul: SoulService,
        *,
        on_agent_initiated: AgentInitiatedNotify | None = None,
    ) -> None:
        self._soul = soul
        self._on_agent_initiated = on_agent_initiated

    @property
    def _speak(self):
        return self._soul._ensure_speak_service()

    def initiate_proactive(self, inbound: ProactiveInitiateInbound) -> ProactiveInitiateAck:
        text = inbound.message.strip()
        if not text and inbound.package is not None:
            text = inbound.package.summary.strip()
        if not text:
            return ProactiveInitiateAck(
                ok=False,
                reason="empty proactive message",
                session_id=inbound.session_id,
            )

        channel_id = inbound.channel_id.strip()
        base_sid = inbound.base_session_id.strip() or inbound.session_id.strip()
        if not channel_id and base_sid:
            channel_id = self._soul.hydrate_speak_channel(base_sid) or base_sid

        session_id = inbound.session_id.strip()
        if not session_id:
            session_id = base_sid if inbound.append else f"proactive-{uuid.uuid4()}"

        snap = self._soul.presence.snapshot(session_id)
        if not inbound.append and snap.expectation.value in _BLOCKED_PROACTIVE:
            return ProactiveInitiateAck(
                ok=False,
                blocked=True,
                reason="interaction expectation blocks proactive speak",
                session_id=session_id,
                channel_id=channel_id,
            )

        if channel_id:
            self._soul.align_speak_visitor(session_id, channel_id)

        proactive_intent_id = inbound.proactive_intent_id.strip() or str(uuid.uuid4())
        agent_initiated = not inbound.append

        if agent_initiated:
            self._soul.start_dialogue_session(
                session_id,
                trigger="proactive_outbound",
            )
            self._soul.presence.ingest(
                PresenceEvent.proactive_open(session_id, wait_reply=inbound.wait_reply),
            )

        if not inbound.append:
            self._soul.dispatch(SoulRequest(
                domain=SoulDomain.speak,
                action=SpeakAction.OPEN_OUTBOUND,
                payload={
                    "session_id": session_id,
                    "message": text,
                    "proactive_intent_id": proactive_intent_id,
                },
            ))

        package = inbound.package
        package_dict = package.to_dict() if package is not None else {}
        share_line = str(package_dict.get("summary", ""))
        narration_parts = [
            part for part in (inbound.presence_narrative.strip(), share_line) if part
        ]
        narration = "\n".join(narration_parts)

        delivered = self._speak.deliver_agent_message(
            session_id=session_id,
            message=text,
            user_text="",
            narration=narration,
            proactive_intent_id=proactive_intent_id,
            record=True,
        )

        exp = inbound.expectation
        if inbound.append or not inbound.wait_reply:
            exp = Expectation.optional
        self._soul.presence.bind(session_id, expectation=exp)

        if agent_initiated:
            self._soul.presence.ingest(PresenceEvent.proactive_delivered(session_id))

        display = inbound.agent_display_name.strip() or self._resolve_agent_display_name()
        banner = f"【{display}发来一条通信】°"
        ui_payload = {
            "type": "agent_proactive_session",
            "session_id": session_id,
            "channel_id": channel_id,
            "message": text,
            "banner": banner,
            "agent_display_name": display,
            "proactive_intent_id": proactive_intent_id,
            "agent_initiated": True,
            "wait_reply": inbound.wait_reply,
            "source": inbound.source,
        }
        self._emit_stream_agent_initiated(session_id, ui_payload)
        if self._on_agent_initiated is not None:
            self._on_agent_initiated(ui_payload)

        return ProactiveInitiateAck(
            ok=True,
            session_id=session_id,
            channel_id=channel_id,
            message=text,
            proactive_intent_id=proactive_intent_id,
            agent_initiated=agent_initiated,
            append=inbound.append,
            ui=ui_payload,
            reason=str(delivered.get("exchange_id", "")),
        )

    def _resolve_agent_display_name(self) -> str:
        snap = self._soul.get_persona_snapshot()
        profile = snap.get("profile") if isinstance(snap, dict) else {}
        if isinstance(profile, dict):
            name = str(profile.get("name", "")).strip()
            if name:
                return name
        name = str(snap.get("name", "")).strip() if isinstance(snap, dict) else ""
        return name or "Agent"

    def _emit_stream_agent_initiated(
        self,
        session_id: str,
        ui_payload: dict[str, Any],
    ) -> None:
        port = self._soul.speak_outbound.stream_port
        if port is None:
            return
        port.emit(
            session_id,
            SpeakStreamEvent(
                kind="state",
                text=ui_payload.get("banner", ""),
                final=True,
                meta={
                    "tag": "agent_initiated",
                    "agent_initiated": True,
                    **ui_payload,
                },
            ),
        )
