from __future__ import annotations

import json
from pathlib import Path

from agent.soul.presence import (
    CaptureEvent,
    PresenceContext,
    PresenceEvent,
    SpeakRequest,
    PresenceService,
    PresenceState,
    PresenceStateStore,
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
    requests: list[SpeakRequest] = []
    presence_svc = PresenceService(on_speak_request=requests.append)
    result = presence_svc.capture_evolution(
        CaptureEvent.wander(
            "tao",
            hint="想聊聊",
            salience=0.7,
            share_desire=ShareDesire.eager,
        ),
    )
    assert result.speak_request is not None
    assert result.speak_request.reason == "想聊聊"
    assert result.speak_request.share_desire == ShareDesire.eager
    assert result.speak_request.package.count == 1
    assert len(requests) == 1
    assert requests[0].impulse_level >= share_desire_weight(ShareDesire.moderate)
    assert presence_svc.snapshot("tao").impulse_level < share_desire_weight(ShareDesire.eager)
    assert presence_svc.share_buffer_size("tao") == 0


def test_gate_skips_mild_share_desire_alone():
    requests: list[SpeakRequest] = []
    presence_svc = PresenceService(on_speak_request=requests.append)
    result = presence_svc.capture_evolution(
        CaptureEvent.story_beat(
            "tao",
            hint="有点想说",
            share_desire=ShareDesire.mild,
        ),
    )
    assert result.speak_request is None
    assert not requests
    assert presence_svc.share_buffer_size("tao") == 1


def test_gate_skips_when_already_required():
    requests: list[SpeakRequest] = []
    presence_svc = PresenceService(on_speak_request=requests.append)
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
    requests: list[SpeakRequest] = []
    presence_svc = PresenceService(on_speak_request=requests.append)
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
    requests: list[SpeakRequest] = []
    presence_svc = PresenceService(on_speak_request=requests.append)
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


def test_presence_state_five_dimensions():
    state = PresenceState()
    payload = state.to_dict()
    assert set(payload.keys()) == {
        "affect",
        "somatic",
        "cognition",
        "perception",
        "expectation",
    }
    assert payload["affect"] == {"narrative": ""}
    assert payload["somatic"] == {"narrative": ""}
    assert payload["cognition"] == {"working_memory": "", "thinking": ""}
    assert payload["perception"] == {"narrative": ""}
    assert payload["expectation"]["toward_user"] == 0.0


def test_presence_state_renders_narrative():
    state = PresenceState()
    state.affect.narrative = "心里有些期待"
    state.somatic.narrative = "身体还算放松"
    state.cognition.working_memory = "记得用户刚才的问题"
    state.cognition.thinking = "我在整理怎么回答"
    state.perception.narrative = "周围很安静"
    rendered = state.render()
    assert "心里有些期待" in rendered
    assert "身体还算放松" in rendered
    assert "记得用户刚才的问题" in rendered
    assert "周围很安静" in rendered


def test_presence_store_migrates_legacy_behavior(tmp_path: Path):
    legacy = {
        "sessions": {
            "tao": {
                "affect": {"valence": "calm", "intensity": 0.2, "mood": ""},
                "behavior": {
                    "expectation": "required",
                    "impulse_level": 0.4,
                    "impulse_reason": "legacy",
                },
                "motivation": {"share_desire": "moderate"},
                "environment": {"setting": "书房", "stimuli": ["雨声"]},
            }
        }
    }
    path = tmp_path / "presence_state.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    store = PresenceStateStore(str(tmp_path))
    loaded = store.load_sessions()["tao"]
    assert loaded.interaction.expectation == Expectation.required
    assert loaded.interaction.impulse_reason == "legacy"
    assert loaded.interaction.share_desire == ShareDesire.moderate
    assert "书房" in loaded.state.perception.narrative
    assert "雨声" in loaded.state.perception.narrative
    assert loaded.state.affect.narrative == "我感到calm"
