from __future__ import annotations

from agent.soul.speak.io.outbound.execute import execute_outbound, outbound_from_ops
from agent.soul.speak.io.outbound.protocol import OutboundOp
from agent.soul.speak.io.outbound.render_protocol import (
    SPEAK_RENDER_FIELDS,
    field_for_stream_kind,
    render_meta,
)
from agent.soul.speak.io.outbound.stream.sanitize import sanitize_stream_event
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent
from agent.soul.speak.responders.request_driven import interpret_role_output
from agent.soul.speak.responders.request_driven.delivery_bridge import (
    execute_timeline_sync,
    timeline_to_outbound_request,
)


def test_render_meta_carries_protocol_keys():
    meta = render_meta("body", phase="delta", wait_ms=None, extra={"role_op": "body"})
    assert meta["field"] == "body"
    assert meta["label"] == "body"
    assert meta["phase"] == "delta"
    assert meta["role_op"] == "body"


def test_character_timeline_emits_one_speak_with_render_time():
    timeline = interpret_role_output("<speak>你好</speak>")
    request = timeline_to_outbound_request(timeline, session_id="s1", finish=True)
    events: list[SpeakStreamEvent] = []

    def _emit(_sid: str, event: SpeakStreamEvent) -> None:
        events.append(event)

    execute_outbound(request, emit_fn=_emit, sleep_fn=lambda _s: None)
    fields = [e.meta.get("field") for e in events]
    assert fields == ["typing", "speak", "finish"]
    assert set(fields) <= SPEAK_RENDER_FIELDS
    assert all(field_for_stream_kind(e.kind, e.meta) == e.meta.get("field") for e in events)
    assert events[0].meta["render_time_ms"] > 0
    speak = next(e for e in events if e.kind == "speak")
    assert speak.meta["wait_ms"] > 0
    assert speak.meta["wait_ms"] == speak.meta["render_time_ms"]


def test_execute_timeline_sync_aligns_fields():
    timeline = interpret_role_output("<speak>你好</speak>")
    result = execute_timeline_sync(timeline, sleep_fn=lambda _s: None)
    assert [e.meta.get("field") for e in result.events] == ["typing", "speak"]


def test_sanitize_does_not_coerce_wait_to_session_state():
    event = SpeakStreamEvent(
        kind="state",
        text="wait",
        meta=render_meta("wait", wait_ms=0, seconds=0.0, extra={"role_op": "wait"}),
    )
    out = sanitize_stream_event(event)
    assert out.meta.get("field") == "wait"
    assert "session_state" not in out.meta
    assert out.text == "wait"


def test_sanitize_backfills_field_for_speak():
    event = SpeakStreamEvent(kind="speak", text="hi", meta={})
    out = sanitize_stream_event(event)
    assert out.meta.get("field") == "speak"
    assert out.meta.get("label") == "speak"
    assert int(out.meta.get("wait_ms") or 0) > 0
    assert out.meta.get("wait_ms") == out.meta.get("render_time_ms")


def test_sanitize_does_not_pace_delta_chunks():
    event = SpeakStreamEvent(
        kind="speak",
        text="hi",
        meta=render_meta("speak", phase="delta"),
    )
    out = sanitize_stream_event(event)
    assert int(out.meta.get("wait_ms") or 0) == 0


def test_outbound_ops_emit_protocol_fields():
    request = outbound_from_ops(
        "s1",
        [
            OutboundOp(kind="think", text="想"),
            OutboundOp(kind="action", text="举手"),
            OutboundOp(kind="speak", text="嗨"),
            OutboundOp(kind="finish", final=True),
        ],
    )
    events: list[SpeakStreamEvent] = []
    execute_outbound(request, emit_fn=lambda _s, e: events.append(e), sleep_fn=lambda _s: None)
    assert [e.meta["field"] for e in events] == [
        "thought",
        "typing",
        "body",
        "typing",
        "speak",
        "finish",
    ]
    body_typing = next(e for e in events if e.meta.get("render_target") == "body")
    assert body_typing.kind == "agent_typing"
    assert body_typing.meta["render_time_ms"] > 0
    assert body_typing.meta["wait_ms"] == body_typing.meta["render_time_ms"]
    body = next(e for e in events if e.kind == "action")
    assert body.meta["wait_ms"] > 0
    assert body.meta["wait_ms"] == body.meta["render_time_ms"]
    speak_typing = next(
        e for e in events
        if e.kind == "agent_typing" and e.meta.get("render_target") == "speak"
    )
    assert speak_typing.meta["render_time_ms"] > 0
    speak = next(e for e in events if e.kind == "speak")
    assert speak.meta["wait_ms"] > 0
    assert speak.meta["wait_ms"] == speak.meta["render_time_ms"]


def test_body_speak_alternate_keeps_order_and_typing():
    timeline = interpret_role_output(
        "<body action>抬手</body action><speak>嗨</speak>"
        "<body action>笑</body action><speak>在呢</speak>"
    )
    request = timeline_to_outbound_request(timeline, session_id="s1", finish=True)
    events: list[SpeakStreamEvent] = []
    execute_outbound(request, emit_fn=lambda _s, e: events.append(e), sleep_fn=lambda _s: None)
    visible = [e for e in events if e.meta.get("field") in ("typing", "body", "speak")]
    assert [e.meta.get("field") for e in visible] == [
        "typing",
        "speak",
        "typing",
        "speak",
    ]
    orders = [e.meta.get("order") for e in visible if e.meta.get("field") != "typing"]
    assert orders == [0, 1]
    contents = [e for e in visible if e.meta.get("field") == "speak"]
    assert all(int(e.meta.get("wait_ms") or 0) > 0 for e in contents)
    assert all(e.meta.get("wait_ms") == e.meta.get("render_time_ms") for e in contents)


def test_execute_holds_before_body_and_speak():
    request = outbound_from_ops(
        "s1",
        [
            OutboundOp(kind="action", text="举手"),
            OutboundOp(kind="speak", text="嗨"),
            OutboundOp(kind="finish", final=True),
        ],
    )
    slept: list[float] = []
    execute_outbound(request, emit_fn=lambda _s, e: None, sleep_fn=slept.append)
    assert len(slept) == 2
    assert all(hold > 0.3 for hold in slept)


def test_timeline_silence_is_not_pushed_to_outbound():
    timeline = interpret_role_output(
        "<body action>低头摆正工具</body action>[speak_action:silence 0]"
    )
    request = timeline_to_outbound_request(timeline, session_id="s1", finish=True)
    assert all(op.kind != "silence" for op in request.ops)
    assert all(op.kind != "action" for op in request.ops)


def test_silent_reply_emits_retracted_typing_before_finish():
    request = outbound_from_ops(
        "s1",
        [OutboundOp(kind="finish", final=True)],
        user_text="在吗",
    )
    events: list[SpeakStreamEvent] = []

    execute_outbound(request, emit_fn=lambda _s, e: events.append(e), sleep_fn=lambda _s: None)

    assert [event.kind for event in events] == ["agent_typing", "finish"]
    assert events[0].meta["render_retracted"] is True
    assert events[0].meta["render_time_ms"] > 0
