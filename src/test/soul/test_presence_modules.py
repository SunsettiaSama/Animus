from __future__ import annotations

from agent.soul.drive import (
    CaptureEvent,
    CaptureResult,
    DriveContext,
    DriveEvent,
    DriveGate,
    DriveState,
    ShareDesire,
    apply_evolution_impulse,
    enqueue_share_event,
)
from agent.soul.drive.share_desire import share_desire_weight


def test_apply_evolution_impulse_uses_share_desire_weight():
    state = DriveState()
    note = apply_evolution_impulse(
        state,
        CaptureEvent.wander(
            "tao",
            hint="反刍线索",
            salience=0.4,
            share_desire=ShareDesire.moderate,
        ),
    )
    assert state.impulse_level == share_desire_weight(ShareDesire.moderate)
    assert state.share_desire == ShareDesire.moderate
    assert state.impulse_reason == "反刍线索"
    assert "wander" in note


def test_mild_share_desire_accumulates_slowly():
    state = DriveState()
    apply_evolution_impulse(
        state,
        CaptureEvent.story_beat(
            "tao",
            hint="一点念头",
            share_desire=ShareDesire.mild,
        ),
    )
    assert state.impulse_level == share_desire_weight(ShareDesire.mild)
    assert DriveGate().evaluate(
        CaptureResult(
            session_id="tao",
            event=CaptureEvent.story_beat("tao", hint="一点念头"),
            before=DriveState(),
            after=state.copy(),
        )
    ) is None


def test_capture_routes_boundary_to_transition():
    from agent.soul.drive import DriveCapture, capture_event_from_drive

    capture = DriveCapture()
    state = DriveState()
    result = capture.ingest(
        state,
        capture_event_from_drive(DriveEvent.user_text("tao")),
        DriveContext(line_open=False),
    )
    assert result.boundary is True
    assert state.expectation.value == "required"


def test_capture_routes_evolution_to_impulse():
    from agent.soul.drive import DriveCapture

    capture = DriveCapture()
    state = DriveState()
    result = capture.ingest(
        state,
        CaptureEvent.landmark("tao", intention="去海边走走"),
        DriveContext(),
    )
    assert result.boundary is False
    assert state.impulse_level == 0.0
    assert state.share_desire == ShareDesire.none
    assert "海边" in state.impulse_reason


def test_gate_breaks_on_eager_share_desire():
    from agent.soul.drive import DriveCapture, ShareBuffer, enqueue_share_event

    state = DriveState()
    capture = DriveCapture()
    buffer = ShareBuffer()
    event = CaptureEvent.wander(
        "tao",
        hint="想说话",
        salience=0.8,
        share_desire=ShareDesire.eager,
    )
    result = capture.ingest(state, event, DriveContext())
    enqueue_share_event(buffer, event)
    outbound = DriveGate().evaluate(result, buffer)
    assert outbound is not None
    assert outbound.reason == "想说话"
    assert outbound.share_desire == ShareDesire.eager
    assert outbound.package.count == 1


def test_gate_breaks_after_multiple_mild_events():
    from agent.soul.drive import DriveCapture, ShareBuffer, enqueue_share_event

    state = DriveState()
    capture = DriveCapture()
    buffer = ShareBuffer()
    for hint in ("慢慢想说", "还有一件", "第三件", "第四件"):
        event = CaptureEvent.story_beat(
            "tao",
            hint=hint,
            salience=0.4,
            share_desire=ShareDesire.mild,
        )
        capture.ingest(state, event, DriveContext())
        enqueue_share_event(buffer, event)
    result = capture.ingest(
        state,
        CaptureEvent.story_beat(
            "tao",
            hint="慢慢想说",
            share_desire=ShareDesire.mild,
        ),
        DriveContext(),
    )
    enqueue_share_event(buffer, result.event)
    outbound = DriveGate().evaluate(result, buffer)
    assert outbound is not None
    assert outbound.package.count == 5
    assert "另有" in outbound.reason
    assert outbound.share_desire in (ShareDesire.mild, ShareDesire.moderate)
