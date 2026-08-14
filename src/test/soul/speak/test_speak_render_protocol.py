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


def test_character_timeline_events_expose_render_fields():
    timeline = interpret_role_output(
        "[think]观察一下[/think]"
        "<speak action>wait 0</speak action>"
        "<speak context>你好</speak context>"
        "<speak action>emit</speak action>"
        "<body action>点头</body action>"
        "<speak action>silence 0</speak action>"
    )
    request = timeline_to_outbound_request(timeline, session_id="s1", finish=True)
    events: list[SpeakStreamEvent] = []

    def _emit(_sid: str, event: SpeakStreamEvent) -> None:
        events.append(event)

    execute_outbound(request, emit_fn=_emit, sleep_fn=lambda _s: None)
    fields = [e.meta.get("field") for e in events]
    assert fields == ["thought", "wait", "speak", "body", "silence", "finish"]
    assert set(fields) <= SPEAK_RENDER_FIELDS
    assert all(field_for_stream_kind(e.kind, e.meta) == e.meta.get("field") for e in events)


def test_execute_timeline_sync_aligns_fields():
    timeline = interpret_role_output(
        "[think]观察一下[/think]"
        "<speak action>wait 0</speak action>"
        "<speak context>你好</speak context>"
        "<speak action>emit</speak action>"
        "<body action>点头</body action>"
    )
    result = execute_timeline_sync(timeline, sleep_fn=lambda _s: None)
    assert [e.meta.get("field") for e in result.events] == [
        "thought",
        "wait",
        "speak",
        "body",
    ]


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
    assert [e.meta["field"] for e in events] == ["thought", "body", "speak", "finish"]
