from __future__ import annotations

from agent.soul.presence import (
    CaptureEvent,
    PresenceContext,
    PresenceEvent,
    PresenceOutboundRequest,
    PresenceService,
    Expectation,
    ShareDesire,
)
from agent.soul.presence.share_desire import share_desire_weight
from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult


def _heartbeat_result(*, hint: str, intensity: float) -> MemoryHeartbeatResult:
    return MemoryHeartbeatResult(
        signal=EmotionalSignal(
            narrative_hint=hint,
            intensity=intensity,
        ),
    )


def test_capture_wander_is_disabled_for_raw_signal():
    presence_svc = PresenceService()
    result = presence_svc.capture_wander(
        _heartbeat_result(hint="想起上次对话", intensity=0.2),
    )
    assert result is None
    snap = presence_svc.snapshot("tao")
    assert snap.impulse_level == 0.0
    assert snap.ignite_reason == ""
    assert snap.expectation == Expectation.none


def test_consider_heartbeat_signal_skips_empty_hint():
    presence_svc = PresenceService()
    result = presence_svc.consider_heartbeat_signal(
        _heartbeat_result(hint="", intensity=0.7),
    )
    assert result is None
    assert presence_svc.snapshot("tao").impulse_level == 0.0


def test_gate_emits_outbound_when_eager_share_desire():
    requests: list[PresenceOutboundRequest] = []
    presence_svc = PresenceService(on_outbound_request=requests.append)
    result = presence_svc.capture_evolution(
        CaptureEvent.wander(
            "tao",
            hint="想聊聊",
            salience=0.7,
            share_desire=ShareDesire.eager,
        ),
    )
    assert result.outbound_request is not None
    assert result.outbound_request.reason == "想聊聊"
    assert result.outbound_request.share_desire == ShareDesire.eager
    assert result.outbound_request.package.count == 1
    assert len(requests) == 1
    assert requests[0].impulse_level >= share_desire_weight(ShareDesire.moderate)
    assert presence_svc.snapshot("tao").impulse_level < share_desire_weight(ShareDesire.eager)
    assert presence_svc.share_buffer_size("tao") == 0


def test_gate_skips_mild_share_desire_alone():
    requests: list[PresenceOutboundRequest] = []
    presence_svc = PresenceService(on_outbound_request=requests.append)
    result = presence_svc.capture_evolution(
        CaptureEvent.story_beat(
            "tao",
            hint="有点想说",
            share_desire=ShareDesire.mild,
        ),
    )
    assert result.outbound_request is None
    assert not requests
    assert presence_svc.share_buffer_size("tao") == 1


def test_gate_skips_when_already_required():
    requests: list[PresenceOutboundRequest] = []
    presence_svc = PresenceService(on_outbound_request=requests.append)
    presence_svc.bind("tao", expectation=Expectation.required)
    presence_svc.capture_evolution(
        CaptureEvent.wander(
            "tao",
            hint="又想聊",
            salience=0.9,
            share_desire=ShareDesire.eager,
        ),
    )
    assert not requests


def test_external_session_start_flushes_accumulated_impulse():
    requests: list[PresenceOutboundRequest] = []
    presence_svc = PresenceService(on_outbound_request=requests.append)
    presence_svc.bind("tao", expectation=Expectation.required)
    presence_svc.capture_evolution(
        CaptureEvent.story_beat(
            "tao",
            hint="我有件事想说",
            share_desire=ShareDesire.moderate,
        ),
    )
    assert presence_svc.snapshot("tao").impulse_level > 0.0
    result = presence_svc.ingest(
        PresenceEvent.user_text("tao"),
        context=PresenceContext(line_open=False),
    )
    assert len(requests) == 1
    assert requests[0].source == "external_start_flush"
    assert requests[0].wait_reply is False
    assert requests[0].reason == "我有件事想说"
    assert result.after.expectation == Expectation.required
    assert result.after.impulse_level == 0.0
    assert presence_svc.share_buffer_size("tao") == 0


def test_manual_flush_requires_saturation():
    requests: list[PresenceOutboundRequest] = []
    presence_svc = PresenceService(on_outbound_request=requests.append)
    presence_svc.bind("tao", expectation=Expectation.required)
    presence_svc.capture_evolution(
        CaptureEvent.story_beat(
            "tao",
            hint="轻微念头",
            share_desire=ShareDesire.mild,
        ),
    )
    assert presence_svc.flush_accumulated("tao", source="external_opportunity_scan") is None
    presence_svc.capture_evolution(
        CaptureEvent.story_beat(
            "tao",
            hint="强烈想说",
            share_desire=ShareDesire.eager,
        ),
    )
    outbound = presence_svc.flush_accumulated("tao", source="external_opportunity_scan")
    assert outbound is not None
    assert outbound.source == "external_opportunity_scan"
    assert outbound.wait_reply is True
