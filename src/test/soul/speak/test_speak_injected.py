from __future__ import annotations

import pytest

from agent.soul.speak.pipelines.request_driven.orchestrator.persona import (
    PersonaComposeService,
    collect_persona_layer,
    distill_self_narrative,
)
from agent.soul.speak.pipelines.request_driven.orchestrator.persona.render import render_traits
from agent.soul.speak.io.inbound.compose import collect_status_injected
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
from unittest.mock import MagicMock


def test_persona_collect_merges_general_and_presence():
    general = "?? A??????"
    persona_snap = persona_snapshot_with_distill(
        dialogue="??????????",
        name="A",
    )
    persona_snap["persona_distill"]["slices"]["general"] = general

    snap = MagicMock()
    snap.state.recent_portrait = None
    snap.state.affect.render.return_value = "focused"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""

    persona = collect_persona_layer(persona_snap=persona_snap, presence_snap=snap)
    assert general in persona.self_narrative
    assert persona.stable_portrait == general
    assert "focused" in persona.state_portrait


def test_speak_forbids_main_portrait_render():
    with pytest.raises(RuntimeError, match="Speak ???????"):
        render_traits({})


def test_persona_collect_raises_without_distill():
    persona_snap = {
        "profile": {"name": "A", "core_traits": ["calm"]},
        "self_concept": {"narrative": "I accompany the user."},
    }
    with pytest.raises(RuntimeError, match="persona_distill missing"):
        collect_persona_layer(persona_snap=persona_snap)


def test_status_collect_only_reads_presence_and_dialogue():
    snap = MagicMock()
    snap.state.affect.render.return_value = "focused"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""

    injected = collect_status_injected(
        presence_snap=snap,
        dialogue_compressed="OLD-BLOCK\n- user talked architecture",
    )
    assert "focused" in injected.presence
    assert "architecture" in injected.dialogue_compressed
    rendered = "".join(injected.render_blocks())
    assert "OLD-BLOCK" not in rendered
    assert "architecture" not in rendered


def test_distill_self_narrative_fallback_without_llm():
    narrative = distill_self_narrative(
        None,
        stable_portrait="?? A????",
        state_portrait="???????",
    )
    assert "?? A" in narrative
    assert "??????" in narrative


class _Persona:
    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict:
        return persona_snapshot_with_distill(name="A")


class _Presence:
    def snapshot(self, session_id: str):
        snap = MagicMock()
        snap.state.recent_portrait = None
        snap.state.affect.render.return_value = "calm"
        snap.state.somatic.render.return_value = ""
        snap.state.cognition.thinking = ""
        snap.state.perception.render.return_value = ""
        return snap


def test_persona_compose_service_caches_until_force():
    service = PersonaComposeService(_Persona(), _Presence())
    first = service.compose_and_set(session_id="s1", turn_index=1)
    second = service.compose_and_set(session_id="s1", turn_index=2)
    assert first.version == second.version
    assert first.self_narrative == second.self_narrative

    third = service.compose_and_set(session_id="s1", turn_index=3, force=True)
    assert third.version == first.version + 1
