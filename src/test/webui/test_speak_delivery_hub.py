from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from agent.adapters.react_bridge import (
    first_spoken_line,
    queue_agent_proactive_session,
    wire_soul_agent_initiated_notify,
)
from agent.soul.speak.io.outbound.bus import SpeakOutboundBus
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent
from webui.speak_delivery_hub import WebUISpeakDeliveryHub
from webui.speak_typing_sim import SimulatedTypingStreamPort
from webui.state import AppState


@dataclass
class _RecordingPort:
    events: list[tuple[str, SpeakStreamEvent]] = field(default_factory=list)

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        self.events.append((session_id, event))


def test_stream_events_route_only_to_exact_registered_session():
    hub = WebUISpeakDeliveryHub()
    first = _RecordingPort()
    second = _RecordingPort()
    hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
        port=first,
        put_payload=lambda _payload: None,
    )
    hub.register(
        session_id="s2",
        channel_id="c2",
        gen_id="g2",
        port=second,
        put_payload=lambda _payload: None,
    )

    hub.begin_client_turn("live:c1")
    hub.emit("live:c1", SpeakStreamEvent(kind="speak", text="only s1"))
    hub.end_client_turn("live:c1")

    assert [event.text for _, event in first.events] == ["only s1"]
    assert second.events == []


def test_online_proactive_waits_until_client_turn_finishes():
    hub = WebUISpeakDeliveryHub()
    port = _RecordingPort()
    frames: list[dict] = []
    hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
        port=port,
        put_payload=frames.append,
    )
    hub.begin_client_turn("live:c1")

    assert hub.enqueue_proactive({
        "session_id": "s1",
        "channel_id": "c1",
        "message": "after user turn",
    }) is True
    assert frames == []
    assert port.events == []

    hub.end_client_turn("live:c1")

    assert [frame["type"] for frame in frames] == ["turn_start", "turn_finish"]
    assert port.events[0][1].text == "after user turn"


def test_offline_proactive_payload_drains_when_connection_ready():
    bus = SpeakOutboundBus(create_ui_timeout_sec=2.0)
    hub = WebUISpeakDeliveryHub()
    bus.bind_stream_port(hub)
    notify = SimpleNamespace(items=[])

    def _publish(item):
        notify.items.append(dict(item))
        return True

    bus.attach_notify_port(SimpleNamespace(publish=_publish))
    payload = {
        "session_id": "proactive-1",
        "channel_id": "browser-1",
        "message": "主动内容",
        "proactive_intent_id": "intent-1",
        "source": "heartbeat",
    }
    result = bus.enqueue_proactive(payload)
    assert result["delivered"] is False
    assert result["status"] == "awaiting_ui"

    port = _RecordingPort()
    frames: list[dict] = []
    hub.register(
        session_id="proactive-1",
        channel_id="browser-1",
        gen_id="g1",
        port=port,
        put_payload=frames.append,
    )
    bus.resolve_create_ui("intent-1", accepted=True, channel_id="browser-1")

    assert [frame["type"] for frame in frames] == ["turn_start", "turn_finish"]
    assert frames[1]["answer"] == "主动内容"
    assert [event.kind for _, event in port.events] == ["speak", "finish"]
    assert bus.acknowledge_proactive("intent-1", channel_id="browser-1")


def test_delivered_proactive_is_consumed_and_not_redelivered():
    """推出成功即消费：重连不得再推同一 delivery。"""
    bus = SpeakOutboundBus(create_ui_timeout_sec=5.0)
    hub = WebUISpeakDeliveryHub()
    bus.bind_stream_port(hub)
    bus.attach_notify_port(SimpleNamespace(publish=lambda _item: True))
    payload = {
        "session_id": "s1",
        "channel_id": "c1",
        "message": "reliable",
        "proactive_intent_id": "intent-1",
        "created_at": "2026-08-16T02:56:00+00:00",
    }
    bus.enqueue_proactive(payload)

    first_frames: list[dict] = []
    unregister = hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
        port=_RecordingPort(),
        put_payload=first_frames.append,
    )
    assert [frame["type"] for frame in first_frames] == ["turn_start", "turn_finish"]
    assert first_frames[0]["created_at"] == "2026-08-16T02:56:00+00:00"
    assert first_frames[1]["created_at"] == "2026-08-16T02:56:00+00:00"
    unregister()

    second_frames: list[dict] = []
    hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g2",
        port=_RecordingPort(),
        put_payload=second_frames.append,
    )
    assert second_frames == []
    assert bus.snapshot()["proactive_pending"] == {}


def test_channel_less_proactive_is_rejected():
    hub = WebUISpeakDeliveryHub()
    payload = {
        "session_id": "scheduled-1",
        "channel_id": "",
        "message": "scheduled",
    }

    with pytest.raises(ValueError, match="channel_id"):
        hub.enqueue_proactive(payload)


def test_proactive_payload_flushes_through_simulated_port():
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    inner = _RecordingPort()
    port = SimulatedTypingStreamPort(inner=inner, loop=loop)
    frames: list[dict] = []
    finished = threading.Event()

    def _put_payload(payload: dict) -> None:
        frames.append(payload)
        if payload["type"] == "turn_finish":
            hub.acknowledge_proactive("s1", "c1", payload["delivery_id"])
            if len(
                [frame for frame in frames if frame["type"] == "turn_finish"]
            ) == 2:
                finished.set()

    hub = WebUISpeakDeliveryHub()
    hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
        port=port,
        put_payload=_put_payload,
    )

    assert hub.enqueue_proactive({
        "session_id": "s1",
        "channel_id": "c1",
        "message": "逐字出现",
    }) is True
    assert hub.enqueue_proactive({
        "session_id": "s1",
        "channel_id": "c1",
        "message": "第二条",
    }) is True
    assert finished.wait(timeout=3.0)
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2.0)
    loop.close()

    assert [frame["type"] for frame in frames] == [
        "turn_start",
        "turn_finish",
        "turn_start",
        "turn_finish",
    ]
    simulated = [
        event
        for _, event in inner.events
        if event.kind == "speak" and event.meta.get("phase") == "simulated"
    ]
    assert [event.text for event in simulated] == ["逐字出现", "第二条"]


def test_proactive_sse_notification_contains_metadata_only():
    from agent.adapters.react_bridge import _AppStateSpeakNotifyPort

    loop = asyncio.new_event_loop()
    notify_queue: asyncio.Queue = asyncio.Queue()
    hub = WebUISpeakDeliveryHub()
    state = SimpleNamespace(
        speak_delivery_hub=hub,
        notify_queue=notify_queue,
        main_event_loop=loop,
        notify_subscribers=[("c1", notify_queue)],
        publish_notify=lambda item: (
            notify_queue.put_nowait(item) or True
        ),
    )
    bus = SpeakOutboundBus(create_ui_timeout_sec=0.05)
    bus.bind_stream_port(hub)
    bus.attach_notify_port(_AppStateSpeakNotifyPort(state))
    snaps: list[dict] = []
    bus.bind_snapshot_sink(snaps.append)
    payload = {
        "session_id": "s1",
        "channel_id": "c1",
        "message": "must stay off SSE",
        "banner": "also visible content",
        "source": "presence",
        "proactive_intent_id": "intent-meta",
    }

    bus.enqueue_proactive(payload)
    loop.run_until_complete(asyncio.sleep(0.08))
    item = notify_queue.get_nowait()
    loop.close()

    assert item["type"] in {"create_ui_request", "proactive_available"}
    assert item["session_id"] == "live:c1"
    assert "message" not in item
    assert "banner" not in item


def test_first_spoken_line_prefers_speak_context_and_first_sentence():
    tagged = (
        "<speak action>wait 1</speak action>"
        "<speak context>嘿，这儿呢！我正在看标本。</speak context>"
    )
    assert first_spoken_line(tagged) == "嘿，这儿呢！"
    assert first_spoken_line("第一句。第二句。") == "第一句。"


def test_offline_proactive_persists_unread_history_and_sends_bark(tmp_path):
    from agent.adapters.react_bridge import _AppStateSpeakNotifyPort

    loop = asyncio.new_event_loop()
    notify_queue: asyncio.Queue = asyncio.Queue()
    hub = WebUISpeakDeliveryHub()
    bark = SimpleNamespace(sent=[], _cfg=SimpleNamespace(enabled=True))

    def _send(title, body, device_key=None):
        del device_key
        bark.sent.append((title, body))

    bark.send = _send
    state = SimpleNamespace(
        speak_delivery_hub=hub,
        notify_queue=notify_queue,
        main_event_loop=loop,
        notify_subscribers=[],
        publish_notify=lambda _item: False,
        history_dir=str(tmp_path),
        bark_notifier=bark,
    )
    bus = SpeakOutboundBus(create_ui_timeout_sec=0.05)
    bus.bind_stream_port(hub)
    bus.attach_notify_port(_AppStateSpeakNotifyPort(state))
    bus.bind_snapshot_sink(lambda payload: queue_agent_proactive_session(state, payload))
    payload = {
        "session_id": "proactive-1",
        "channel_id": "c1",
        "message": "今晚月色很好。要不要出来走走？",
        "banner": "【栖灵发来一条通信】°",
        "agent_display_name": "栖灵",
        "proactive_intent_id": "intent-1",
        "source": "presence",
        "create_window": True,
    }

    result = bus.enqueue_proactive(payload)
    loop.run_until_complete(asyncio.sleep(0.08))
    loop.close()

    assert result["status"] == "snapshotted"
    assert bark.sent == [("栖灵", "今晚月色很好。")]
    saved = json.loads((tmp_path / "live_c1.json").read_text(encoding="utf-8"))
    assert saved["proactive_unread"] is True
    assert saved["agent_initiated"] is True
    assert saved["messages"][0]["content"] == payload["message"]
    assert saved["messages"][0]["proactive_intent_id"] == "intent-1"


def test_online_proactive_delivery_does_not_emit_duplicate_sse_wakeup():
    from agent.adapters.react_bridge import _AppStateSpeakNotifyPort

    loop = asyncio.new_event_loop()
    notify_queue: asyncio.Queue = asyncio.Queue()
    hub = WebUISpeakDeliveryHub()
    port = _RecordingPort()
    hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
        port=port,
        put_payload=lambda _payload: None,
    )
    state = SimpleNamespace(
        speak_delivery_hub=hub,
        notify_queue=notify_queue,
        main_event_loop=loop,
        notify_subscribers=[("c1", notify_queue)],
        publish_notify=notify_queue.put_nowait,
    )
    bus = SpeakOutboundBus()
    bus.bind_stream_port(hub)
    bus.attach_notify_port(_AppStateSpeakNotifyPort(state))

    result = bus.enqueue_proactive(
        {
            "session_id": "s1",
            "channel_id": "c1",
            "message": "online",
        },
    )
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()

    assert result["delivered"] is True
    assert notify_queue.empty()
    assert port.events[0][1].text == "online"


def test_soul_notify_wiring_is_idempotent():
    class _Speak:
        def __init__(self) -> None:
            self.notify_ports: list = []
            self.snapshot_sink = None

        def attach_notify_port(self, port) -> None:
            if port not in self.notify_ports:
                self.notify_ports.append(port)

        def bind_outbound_snapshot_sink(self, sink) -> None:
            self.snapshot_sink = sink

    class _Soul:
        def __init__(self) -> None:
            self.handlers: list = []
            self.port = None
            self._speak = _Speak()

        def bind_speak_stream_port(self, port) -> None:
            self.port = port

        def _ensure_speak_service(self):
            return self._speak

        def register_agent_initiated_handler(self, handler) -> None:
            self.handlers.append(handler)

    soul = _Soul()
    state = SimpleNamespace(
        speak_delivery_hub=None,
        speak_notify_soul=None,
        speak_notify_port=None,
        main_event_loop=None,
        publish_notify=lambda _item: False,
    )

    wire_soul_agent_initiated_notify(soul, state)
    wire_soul_agent_initiated_notify(soul, state)

    assert soul.port is state.speak_delivery_hub
    assert soul.handlers == []
    assert len(soul._speak.notify_ports) == 1
    assert callable(soul._speak.snapshot_sink)


def test_proactive_notification_broadcast_is_filtered_by_channel():
    loop = asyncio.new_event_loop()
    state = object.__new__(AppState)
    state.main_event_loop = loop
    state.notify_subscribers = []
    state.speak_delivery_hub = None
    first: asyncio.Queue = asyncio.Queue()
    second: asyncio.Queue = asyncio.Queue()
    state.attach_notify_subscriber("c1", first)
    state.attach_notify_subscriber("c2", second)

    assert state.publish_notify({
        "type": "proactive_available",
        "channel_id": "c2",
        "session_id": "s2",
    }) is True
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()

    assert first.empty()
    assert second.get_nowait()["session_id"] == "s2"


def test_new_notify_subscriber_replays_pending_channel_availability():
    bus = SpeakOutboundBus(create_ui_timeout_sec=5.0)
    hub = WebUISpeakDeliveryHub()
    bus.bind_stream_port(hub)
    bus.attach_notify_port(SimpleNamespace(publish=lambda _item: True))
    bus.enqueue_proactive({
        "session_id": "s2",
        "channel_id": "c2",
        "message": "offline",
        "proactive_intent_id": "intent-2",
    })
    state = object.__new__(AppState)
    state.notify_subscribers = []
    state.speak_delivery_hub = hub
    state.soul_service = SimpleNamespace(
        _ensure_speak_service=lambda: SimpleNamespace(
            _io=SimpleNamespace(outbound=SimpleNamespace(bus=bus))
        )
    )
    queue: asyncio.Queue = asyncio.Queue()

    state.attach_notify_subscriber("c2", queue)

    item = queue.get_nowait()
    assert item["type"] == "create_ui_request"
    assert item["session_id"] == "live:c2"
    assert item["delivery_id"] == "intent-2"
    assert "message" not in item


def test_server_turn_finish_waits_for_simulated_typing_flush():
    async def _run() -> None:
        timeline: list[str] = []

        class _TimelinePort:
            def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
                del session_id
                timeline.append(f"event:{event.kind}")

        loop = asyncio.get_running_loop()
        simulated = SimulatedTypingStreamPort(
            inner=_TimelinePort(),
            loop=loop,
            ms_per_char=0.0,
        )
        hub = WebUISpeakDeliveryHub()
        hub.register(
            session_id="s1",
            channel_id="c1",
            gen_id="g1",
            port=simulated,
            put_payload=lambda payload: timeline.append(payload["type"]),
        )

        hub.enqueue_proactive({
            "session_id": "s1",
            "channel_id": "c1",
            "message": "你好",
        })
        await asyncio.sleep(0.25)

        assert timeline[0] == "turn_start"
        assert timeline.index("event:speak") < timeline.index("turn_finish")
        assert timeline.index("event:finish") < timeline.index("turn_finish")

    asyncio.run(_run())


def test_live_prefix_session_matches_bare_channel_connection():
    hub = WebUISpeakDeliveryHub()
    port = _RecordingPort()
    hub.register(
        session_id="live:abc",
        channel_id="abc",
        gen_id="g1",
        port=port,
        put_payload=lambda _payload: None,
    )
    assert hub.has_connection("live:abc") is True
    assert hub.has_connection("other", channel_id="abc") is True
    assert hub.enqueue_proactive({
        "session_id": "live:abc",
        "channel_id": "live:abc",
        "message": "mapped",
        "proactive_intent_id": "intent-map",
    }) is True
    assert port.events[0][1].text == "mapped"
