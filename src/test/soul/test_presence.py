from __future__ import annotations

import json
from pathlib import Path

from agent.soul.presence import (
    Expectation,
    PresenceContext,
    PresenceEvent,
    PresenceService,
    PresenceState,
    PresenceStateStore,
    ShareDesire,
)
from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult


def _heartbeat_result(*, hint: str, intensity: float) -> MemoryHeartbeatResult:
    return MemoryHeartbeatResult(
        signal=EmotionalSignal(
            narrative_hint=hint,
            intensity=intensity,
        ),
    )


def test_consider_heartbeat_signal_applies_affect_hint():
    presence_svc = PresenceService()
    applied = presence_svc.consider_heartbeat_signal(
        _heartbeat_result(hint="想起上次对话", intensity=0.2),
    )
    assert applied is True
    assert "想起上次对话" in presence_svc.snapshot("tao").state.affect.narrative


def test_consider_heartbeat_signal_skips_low_intensity():
    presence_svc = PresenceService()
    applied = presence_svc.consider_heartbeat_signal(
        _heartbeat_result(hint="想起上次对话", intensity=0.01),
    )
    assert applied is False


def test_external_session_start_discharges_accumulated_impulse():
    presence_svc = PresenceService()
    session = presence_svc._session("tao")
    session.interaction.expectation = Expectation.required
    session.interaction.impulse_level = 0.8
    session.interaction.impulse_reason = "我有件事想说"
    from agent.soul.presence.state import ShareIntent

    session.state.expectation.share_queue.enqueue(
        ShareIntent(topic="我有件事想说", share_desire=ShareDesire.moderate),
    )

    result = presence_svc.ingest(
        PresenceEvent.user_text("tao"),
        context=PresenceContext(line_open=False),
    )
    assert result.impulse_discharge is not None
    assert result.impulse_discharge.source == "external_start_flush"
    assert result.impulse_discharge.wait_reply is False
    assert result.after.expectation == Expectation.required
    assert result.after.impulse_level == 0.0


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


def test_wake_result_normalizes_none_narratives():
    from agent.soul.presence.transition.static.lifecycle import WakeResult

    result = WakeResult(session_id="tao", applied=True, narratives=None, notes=None)
    assert result.narratives == {}
    assert result.notes == []
    assert dict(result.narratives) == {}
