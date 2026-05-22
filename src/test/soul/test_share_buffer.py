from __future__ import annotations

from agent.soul.presence import (
    CaptureEvent,
    PresenceService,
    ShareDesire,
    share_desire_weight,
)


def test_share_buffer_queues_mild_events():
    presence_svc = PresenceService()
    presence_svc.capture_evolution(
        CaptureEvent.story_beat(
            "tao",
            hint="第一个念头",
            salience=0.3,
            share_desire=ShareDesire.mild,
        ),
    )
    presence_svc.capture_evolution(
        CaptureEvent.story_beat(
            "tao",
            hint="第二个念头",
            salience=0.5,
            share_desire=ShareDesire.mild,
        ),
    )
    assert presence_svc.share_buffer_size("tao") == 2


def test_gate_flushes_folded_package_to_top():
    requests = []
    presence_svc = PresenceService(on_outbound_request=requests.append)
    for hint in ("慢慢想说", "还有一件事", "第三件"):
        presence_svc.capture_evolution(
            CaptureEvent.story_beat(
                "tao",
                hint=hint,
                salience=0.4,
                share_desire=ShareDesire.mild,
            ),
        )

    assert len(requests) == 1
    outbound = requests[0]
    package = outbound.package
    assert package.count == 3
    assert package.peak_salience == 0.4
    assert "第三件" not in outbound.reason
    assert "另有 2 条想分享的事" in outbound.reason
    assert presence_svc.share_buffer_size("tao") == 0
    assert presence_svc.snapshot("tao").impulse_level < share_desire_weight(ShareDesire.moderate)


def test_eager_event_emits_single_entry_package():
    requests = []
    presence_svc = PresenceService(on_outbound_request=requests.append)
    presence_svc.capture_evolution(
        CaptureEvent.wander(
            "tao",
            hint="现在就想说",
            salience=0.8,
            share_desire=ShareDesire.eager,
        ),
    )
    assert len(requests) == 1
    package = requests[0].package
    assert package.count == 1
    assert package.summary == "现在就想说"
    assert requests[0].share_desire == ShareDesire.eager
