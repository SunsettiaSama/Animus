from __future__ import annotations

from agent.soul.speak.io.outbound.bus import SpeakOutboundBus
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


class _RecordingNotify:
    def __init__(self, *, reached: bool = False) -> None:
        self.items: list[dict] = []
        self.reached = reached

    def publish(self, item: dict) -> bool:
        self.items.append(dict(item))
        return bool(self.reached)


def test_bus_buffers_stream_until_port_attaches():
    bus = SpeakOutboundBus()
    bus.publish_stream("s1", SpeakStreamEvent(kind="speak", text="hi"))
    assert bus.snapshot()["stream_pending_sessions"]["s1"] == 1
    port = _RecordingStream()
    bus.bind_stream_port(port)
    assert port.events[0][1].text == "hi"
    assert bus.snapshot()["stream_pending_sessions"] == {}


def test_bus_proactive_snapshots_when_frontend_unreachable():
    bus = SpeakOutboundBus(create_ui_timeout_sec=0.05)
    notify = _RecordingNotify(reached=False)
    snaps: list[dict] = []
    bus.attach_notify_port(notify)
    bus.bind_snapshot_sink(snaps.append)
    result = bus.enqueue_proactive(
        {
            "session_id": "proactive-x",
            "channel_id": "c1",
            "message": "你好",
            "create_window": True,
            "proactive_intent_id": "intent-x",
        }
    )
    assert result["delivered"] is False
    assert result["status"] == "snapshotted"
    assert snaps and snaps[0]["message"] == "你好"
    types = [item["type"] for item in notify.items]
    assert "create_ui_request" in types
    assert "proactive_available" in types
    assert notify.items[-1]["create_window"] is True


def test_bus_proactive_delivers_when_stream_connected():
    bus = SpeakOutboundBus()
    stream = _RecordingStream()
    bus.bind_stream_port(stream)
    notify = _RecordingNotify(reached=True)
    bus.attach_notify_port(notify)

    def _enqueue(payload):
        text = payload["message"]
        stream.emit(
            payload["session_id"],
            SpeakStreamEvent(kind="speak", text=text, meta={"proactive": True}),
        )
        return True

    stream.enqueue_proactive = _enqueue  # type: ignore[attr-defined]
    result = bus.enqueue_proactive(
        {
            "session_id": "live:c1",
            "channel_id": "c1",
            "message": "在线",
            "created_at": "2026-08-16T03:00:00+00:00",
        }
    )
    assert result["delivered"] is True
    assert result["payload"]["created_at"] == "2026-08-16T03:00:00+00:00"
    assert notify.items == []
    assert stream.events[0][1].text == "在线"
    assert bus.snapshot()["proactive_pending"] == {}


def test_bus_create_ui_accept_then_deliver():
    bus = SpeakOutboundBus(create_ui_timeout_sec=2.0)
    stream = _RecordingStream()
    stream._online.clear()
    bus.bind_stream_port(stream)
    notify = _RecordingNotify(reached=True)
    bus.attach_notify_port(notify)
    delivered: list[str] = []

    def _enqueue(payload):
        delivered.append(payload["message"])
        return True

    stream.enqueue_proactive = _enqueue  # type: ignore[attr-defined]
    result = bus.enqueue_proactive(
        {
            "session_id": "live:c1",
            "channel_id": "c1",
            "message": "开窗后投递",
            "proactive_intent_id": "intent-ui",
        }
    )
    assert result["status"] == "awaiting_ui"
    assert delivered == []

    stream._online.add("live:c1")
    resolved = bus.resolve_create_ui("intent-ui", accepted=True, channel_id="c1")
    assert resolved["delivered"] is True
    assert delivered == ["开窗后投递"]


def test_bus_create_ui_reject_snapshots():
    bus = SpeakOutboundBus(create_ui_timeout_sec=2.0)
    notify = _RecordingNotify(reached=True)
    snaps: list[dict] = []
    bus.attach_notify_port(notify)
    bus.bind_snapshot_sink(snaps.append)
    bus.enqueue_proactive(
        {
            "session_id": "live:c1",
            "channel_id": "c1",
            "message": "拒绝",
            "proactive_intent_id": "intent-reject",
        }
    )
    resolved = bus.resolve_create_ui("intent-reject", accepted=False, channel_id="c1")
    assert resolved["status"] == "snapshotted"
    assert snaps[0]["message"] == "拒绝"


def test_bus_normalizes_live_prefix_channel():
    bus = SpeakOutboundBus(create_ui_timeout_sec=0.05)
    snaps: list[dict] = []
    bus.bind_snapshot_sink(snaps.append)
    result = bus.enqueue_proactive(
        {
            "session_id": "live:0feacc59-40fa-4422-a58a-d40d36d72d29",
            "channel_id": "live:0feacc59-40fa-4422-a58a-d40d36d72d29",
            "message": "channel fix",
            "proactive_intent_id": "intent-live",
        }
    )
    assert result["payload"]["channel_id"] == "0feacc59-40fa-4422-a58a-d40d36d72d29"
    assert result["payload"]["session_id"] == "live:0feacc59-40fa-4422-a58a-d40d36d72d29"
    assert snaps[0]["channel_id"] == "0feacc59-40fa-4422-a58a-d40d36d72d29"


def test_bus_ack_clears_pending():
    bus = SpeakOutboundBus()
    stream = _RecordingStream()
    bus.bind_stream_port(stream)
    stream.enqueue_proactive = lambda payload: True  # type: ignore[attr-defined]
    bus.enqueue_proactive(
        {
            "session_id": "live:c1",
            "channel_id": "c1",
            "message": "ack me",
            "proactive_intent_id": "intent-ack",
        }
    )
    # 推出成功已消费；ack 幂等
    assert bus.acknowledge_proactive("intent-ack", channel_id="c1")
    assert bus.snapshot()["proactive_pending"] == {}
