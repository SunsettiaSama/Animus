from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.orchestrator import (
    ShareDesireComposer,
    SpeakOrchestrator,
    SpeakGuidanceLayer,
    SpeakPersonaLayer,
    SpeakSceneLayer,
    SpeakSystemLayer,
)
from agent.soul.speak.orchestrator.guidance.share import collect_share_state
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill


def test_compose_persona_and_presence_fields_separated():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(
        name="?A",
        dialogue="??????\n??/???????\n??????????",
    )
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "??"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = "??????"
    snap.state.perception.render.return_value = "???????"
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    presence.snapshot.return_value = snap

    bundle = SpeakOrchestrator(persona, presence).compose("tao", "??")
    system = bundle.build_system()

    assert isinstance(bundle.persona, SpeakPersonaLayer)
    assert isinstance(bundle.scene, SpeakSceneLayer)
    assert isinstance(bundle.system, SpeakSystemLayer)
    assert isinstance(bundle.guidance, SpeakGuidanceLayer)
    assert "??????" in system
    assert "????" in system
    assert "????????" in system
    assert "?????" in system
    assert "??????" not in system
    assert "presence_self_narrative" not in system


def test_compose_injects_share_desire_and_summary():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="?A")
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {
        "share_queue": ShareIntentQueue(
            items=[ShareIntent(topic="???????", share_desire=ShareDesire.moderate)],
        ).to_dict(),
    }
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.moderate
    presence.snapshot.return_value = snap

    bundle = SpeakOrchestrator(persona, presence).compose("tao", "??")
    system = bundle.build_system()

    assert bundle.wants_share is True
    assert "??????" in system
    assert "????" in system
    assert "????" in system
    assert "[0]" in system


def test_collect_share_state_without_queue():
    snap = MagicMock()
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none

    state = collect_share_state(snap)
    assert state.wants_share is False
    assert state.summary == ""
