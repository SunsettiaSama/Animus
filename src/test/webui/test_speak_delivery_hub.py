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
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent
from webui.speak_delivery_hub import WebUISpeakDeliveryHub
from webui.speak_typing_sim import SimulatedTypingStreamPort
from webui.state import AppState
from webui.speak_typing_sim import SimulatedTypingStreamPort


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

    hub.begin_client_turn("s1")
    hub.emit("s1", SpeakStreamEvent(kind="speak", text="only s1"))
    hub.end_client_turn("s1")

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
    hub.begin_client_turn("s1")

    assert hub.enqueue_proactive({
        "session_id": "s1",
        "channel_id": "c1",
        "message": "after user turn",
    }) is True
    assert frames == []
    assert port.events == []

    hub.end_client_turn("s1")

    assert [frame["type"] for frame in frames] == ["turn_start", "turn_finish"]
    assert port.events[0][1].text == "after user turn"


def test_offline_proactive_payload_drains_with_server_turn_framing():
    hub = WebUISpeakDeliveryHub()
    payload = {
        "session_id": "proactive-1",
        "channel_id": "browser-1",
        "message": "主动内容",
        "proactive_intent_id": "intent-1",
        "source": "heartbeat",
    }

    assert hub.enqueue_proactive(payload) is False
    assert hub.pending_count("proactive-1", "browser-1") == 1

    port = _RecordingPort()
    frames: list[dict] = []
    hub.register(
        session_id="proactive-1",
        channel_id="browser-1",
        gen_id="g1",
        port=port,
        put_payload=frames.append,
    )

    assert hub.pending_count("proactive-1", "browser-1") == 1
    assert [frame["type"] for frame in frames] == ["turn_start", "turn_finish"]
    assert frames[0]["server_initiated"] is True
    assert frames[1]["answer"] == "主动内容"
    assert [event.kind for _, event in port.events] == ["speak", "finish"]
    assert port.events[0][1].text == "主动内容"
    assert hub.acknowledge_proactive(
        "proactive-1",
        "browser-1",
        payload["delivery_id"],
    )
    assert hub.pending_count("proactive-1", "browser-1") == 0


def test_unacknowledged_proactive_redelivers_after_reconnect_only():
    hub = WebUISpeakDeliveryHub()
    payload = {
        "session_id": "s1",
        "channel_id": "c1",
        "message": "reliable",
        "proactive_intent_id": "intent-1",
    }
    assert hub.enqueue_proactive(payload) is False

    first_frames: list[dict] = []
    unregister = hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
        port=_RecordingPort(),
        put_payload=first_frames.append,
    )
    unregister()
    second_frames: list[dict] = []
    unregister = hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g2",
        port=_RecordingPort(),
        put_payload=second_frames.append,
    )

    assert [frame["type"] for frame in first_frames] == ["turn_start", "turn_finish"]
    assert [frame["type"] for frame in second_frames] == ["turn_start", "turn_finish"]
    assert hub.acknowledge_proactive("s1", "c1", payload["delivery_id"])
    unregister()

    third_frames: list[dict] = []
    hub.register(
        session_id="s1",
        channel_id="c1",
        gen_id="g3",
        port=_RecordingPort(),
        put_payload=third_frames.append,
    )
    assert third_frames == []


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
    loop = asyncio.new_event_loop()
    notify_queue: asyncio.Queue = asyncio.Queue()
    hub = WebUISpeakDeliveryHub()
    state = SimpleNamespace(
        speak_delivery_hub=hub,
        notify_queue=notify_queue,
        main_event_loop=loop,
        publish_notify=notify_queue.put_nowait,
    )
    payload = {
        "session_id": "s1",
        "channel_id": "c1",
        "message": "must stay off SSE",
        "banner": "also visible content",
        "source": "presence",
    }

    queue_agent_proactive_session(state, payload)
    loop.run_until_complete(asyncio.sleep(0))
    item = notify_queue.get_nowait()
    loop.close()

    assert item["type"] == "proactive_available"
    assert item["session_id"] == "s1"
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
        publish_notify=notify_queue.put_nowait,
        history_dir=str(tmp_path),
        bark_notifier=bark,
    )
    payload = {
        "session_id": "proactive-1",
        "channel_id": "c1",
        "message": "今晚月色很好。要不要出来走走？",
        "banner": "【栖灵发来一条通信】°",
        "agent_display_name": "栖灵",
        "proactive_intent_id": "intent-1",
        "source": "presence",
    }

    queue_agent_proactive_session(state, payload)
    loop.run_until_complete(asyncio.sleep(0))
    item = notify_queue.get_nowait()
    loop.close()

    assert item["type"] == "proactive_available"
    assert item["session_id"] == "proactive-1"
    assert bark.sent == [("栖灵", "今晚月色很好。")]
    saved = json.loads((tmp_path / "proactive-1.json").read_text(encoding="utf-8"))
    assert saved["proactive_unread"] is True
    assert saved["agent_initiated"] is True
    assert saved["messages"][0]["content"] == payload["message"]
    assert saved["messages"][0]["proactive_intent_id"] == "intent-1"


def test_online_proactive_delivery_does_not_emit_duplicate_sse_wakeup():
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
        publish_notify=notify_queue.put_nowait,
    )

    queue_agent_proactive_session(
        state,
        {
            "session_id": "s1",
            "channel_id": "c1",
            "message": "online",
        },
    )
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()

    assert notify_queue.empty()
    assert port.events[0][1].text == "online"


def test_soul_notify_wiring_is_idempotent():
    class _Soul:
        def __init__(self) -> None:
            self.handlers: list = []
            self.port = None

        def bind_speak_stream_port(self, port) -> None:
            self.port = port

        def register_agent_initiated_handler(self, handler) -> None:
            self.handlers.append(handler)

    soul = _Soul()
    state = SimpleNamespace(
        speak_delivery_hub=None,
        speak_notify_soul=None,
    )

    wire_soul_agent_initiated_notify(soul, state)
    wire_soul_agent_initiated_notify(soul, state)

    assert soul.port is state.speak_delivery_hub
    assert len(soul.handlers) == 1


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

    state.publish_notify({
        "type": "proactive_available",
        "channel_id": "c2",
        "session_id": "s2",
    })
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()

    assert first.empty()
    assert second.get_nowait()["session_id"] == "s2"


def test_new_notify_subscriber_replays_pending_channel_availability():
    hub = WebUISpeakDeliveryHub()
    hub.enqueue_proactive({
        "session_id": "s2",
        "channel_id": "c2",
        "message": "offline",
        "proactive_intent_id": "intent-2",
    })
    state = object.__new__(AppState)
    state.notify_subscribers = []
    state.speak_delivery_hub = hub
    queue: asyncio.Queue = asyncio.Queue()

    state.attach_notify_subscriber("c2", queue)

    item = queue.get_nowait()
    assert item["type"] == "proactive_available"
    assert item["session_id"] == "s2"
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
