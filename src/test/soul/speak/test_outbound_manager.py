from __future__ import annotations

from agent.soul.speak.io.outbound.bus import SpeakOutboundBus
from agent.soul.speak.io.outbound.execute import OutboundExecuteResult
from agent.soul.speak.io.outbound.manager import (
    OutboundMessage,
    OutboundMessageManager,
    message_from_request,
    message_from_speak_text,
)
from agent.soul.speak.io.outbound.protocol import OutboundOp, OutboundRequest
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent


class _RecordingStream:
    def __init__(self) -> None:
        self.events: list[tuple[str, SpeakStreamEvent]] = []
        self._online: set[str] = {"live:c1"}

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        self.events.append((session_id, event))

    def has_connection(self, session_id: str, channel_id: str = "") -> bool:
        if channel_id and f"live:{channel_id}" in self._online:
            return True
        return session_id in self._online

    def enqueue_proactive(self, payload: dict) -> bool:
        text = str(payload.get("message") or "")
        self.emit(
            str(payload.get("session_id") or ""),
            SpeakStreamEvent(
                kind="speak",
                text=text,
                meta={"created_at": payload.get("created_at", "")},
            ),
        )
        return True


def test_manager_live_stamps_created_at_once():
    bus = SpeakOutboundBus()
    manager = OutboundMessageManager(bus)
    stream = _RecordingStream()

    def _runner(request: OutboundRequest) -> OutboundExecuteResult:
        return manager.run_execute(request, emit_fn=stream.emit)

    manager.bind_live_runner(_runner)
    request = OutboundRequest(
        session_id="s1",
        ops=(
            OutboundOp(kind="speak", text="你好", meta={"field": "speak"}),
            OutboundOp(kind="finish", text="", final=True, meta={"field": "finish"}),
        ),
        meta={"source": "turn"},
    )
    result = manager.accept_request(request, mode="live")
    assert result.ok
    assert result.mode == "live"
    assert result.message.created_at
    assert all(
        event.meta.get("created_at") == result.message.created_at
        for _, event in stream.events
        if event.kind in {"speak", "finish"}
    )


def test_manager_pending_consumes_on_deliver():
    bus = SpeakOutboundBus()
    manager = OutboundMessageManager(bus)
    stream = _RecordingStream()
    bus.bind_stream_port(stream)
    result = manager.accept_speak_text(
        "live:c1",
        "主动一句",
        mode="pending",
        channel_id="c1",
        source="director",
        created_at="2026-08-16T03:10:00+00:00",
        agent_initiated=True,
        create_window=True,
        proactive_intent_id="intent-mgr",
    )
    assert result.ok
    assert result.status == "delivered"
    assert result.message.created_at == "2026-08-16T03:10:00+00:00"
    assert bus.snapshot()["proactive_pending"] == {}
    assert stream.events[0][1].meta.get("created_at") == "2026-08-16T03:10:00+00:00"


def test_message_from_request_preserves_ops():
    request = OutboundRequest(
        session_id="s1",
        ops=(OutboundOp(kind="outline", text="开场", meta={"field": "outline"}),),
        meta={"created_at": "2026-08-16T01:00:00+00:00"},
    )
    message = message_from_request(request)
    assert message.created_at == "2026-08-16T01:00:00+00:00"
    assert message.ops[0].kind == "outline"
