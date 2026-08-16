from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from agent.soul.speak.io.outbound.bus import SpeakOutboundBus
from agent.soul.speak.io.outbound.execute import OutboundExecuteResult, execute_outbound
from agent.soul.speak.io.outbound.protocol import OutboundRequest
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent

from .builders import (
    message_from_pending_payload,
    message_from_request,
    message_from_speak_text,
    request_from_message,
)
from .unit import OutboundDispatchResult, OutboundMessage

LiveEmitFn = Callable[[str, SpeakStreamEvent], None]
LiveRunner = Callable[[OutboundRequest], OutboundExecuteResult]


class OutboundMessageManager:
    """出站消息管理器：统一编排 live（即时流式）与 pending（主动挂起）投递。

    - 用户回合即时回复 → ``dispatch_live``
    - 导演 / Presence 主动消息 → ``dispatch_pending``
    - ``created_at`` 仅在 accept 时固化一次，下游不得改写成「现在」
    """

    def __init__(self, bus: SpeakOutboundBus) -> None:
        self._bus = bus
        self._live_runner: LiveRunner | None = None

    @property
    def bus(self) -> SpeakOutboundBus:
        return self._bus

    def bind_live_runner(self, runner: LiveRunner | None) -> None:
        self._live_runner = runner

    def accept(self, message: OutboundMessage) -> OutboundDispatchResult:
        msg = message.stamped()
        if msg.mode == "pending":
            return self.dispatch_pending(msg)
        return self.dispatch_live(msg)

    def dispatch_live(
        self,
        message: OutboundMessage,
        *,
        runner: LiveRunner | None = None,
    ) -> OutboundDispatchResult:
        msg = message.stamped()
        if msg.mode != "live":
            msg = replace(msg, mode="live")
        request = request_from_message(msg)
        use_runner = runner or self._live_runner
        if use_runner is None:
            raise RuntimeError("OutboundMessageManager live runner unbound")
        result = use_runner(request)
        return OutboundDispatchResult(
            ok=True,
            mode="live",
            message=msg,
            status="delivered",
            events=list(result.events),
            answer=result.answer or msg.answer_text,
        )

    def dispatch_pending(self, message: OutboundMessage) -> OutboundDispatchResult:
        msg = message.stamped()
        if msg.mode != "pending":
            msg = replace(
                msg,
                mode="pending",
                text=msg.text or msg.answer_text,
            )
        payload = msg.to_pending_payload()
        bus_result = self._bus.enqueue_proactive(payload)
        status = str(bus_result.get("status") or "")
        return OutboundDispatchResult(
            ok=bool(bus_result.get("ok", True)),
            mode="pending",
            message=msg,
            status=status or ("delivered" if bus_result.get("delivered") else "queued"),
            answer=msg.answer_text,
            bus=dict(bus_result),
        )

    def accept_request(
        self,
        request: OutboundRequest,
        *,
        mode: str = "live",
        channel_id: str = "",
        runner: LiveRunner | None = None,
    ) -> OutboundDispatchResult:
        message = message_from_request(request, mode=mode, channel_id=channel_id)
        if mode == "pending":
            return self.dispatch_pending(message)
        return self.dispatch_live(message, runner=runner)

    def accept_pending_payload(self, payload: dict[str, Any]) -> OutboundDispatchResult:
        return self.dispatch_pending(message_from_pending_payload(payload))

    def accept_speak_text(
        self,
        session_id: str,
        text: str,
        *,
        mode: str = "live",
        channel_id: str = "",
        user_text: str = "",
        source: str = "",
        created_at: str = "",
        **pending_kwargs: Any,
    ) -> OutboundDispatchResult:
        message = message_from_speak_text(
            session_id,
            text,
            mode=mode,
            channel_id=channel_id,
            user_text=user_text,
            source=source,
            created_at=created_at,
        )
        if mode == "pending":
            message = replace(
                message,
                mode="pending",
                channel_id=channel_id,
                agent_initiated=bool(pending_kwargs.get("agent_initiated", True)),
                create_window=bool(pending_kwargs.get("create_window", True)),
                wait_reply=bool(pending_kwargs.get("wait_reply", False)),
                proactive_intent_id=str(pending_kwargs.get("proactive_intent_id") or ""),
                banner=str(pending_kwargs.get("banner") or ""),
                agent_display_name=str(pending_kwargs.get("agent_display_name") or ""),
            )
        return self.accept(message)

    def run_execute(
        self,
        request: OutboundRequest,
        *,
        emit_fn: LiveEmitFn,
        session_service: Any = None,
        stream_channel: Any = None,
        should_continue_fn: Callable[[str], bool] | None = None,
        on_done: Callable[[str], None] | None = None,
    ) -> OutboundExecuteResult:
        """底层 live 播放；created_at 已由 message → request 固化。"""
        return execute_outbound(
            request,
            emit_fn=emit_fn,
            session_service=session_service,
            stream_channel=stream_channel,
            should_continue_fn=should_continue_fn,
            on_done=on_done,
        )
