from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.compose.injected import (
    collect_persona_injected,
    collect_status_injected,
)


def test_persona_collect_only_reads_persona_snapshot():
    persona_snap = {
        "profile": {"name": "A", "core_traits": ["calm"]},
        "self_concept": {"narrative": "I accompany the user."},
    }
    injected = collect_persona_injected(persona_snap=persona_snap)
    assert "A" in injected.traits
    assert "accompany" in injected.self_concept


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


def test_persona_and_status_blocks_do_not_cross():
    persona_snap = {
        "profile": {"name": "A"},
        "self_concept": {},
    }
    snap = MagicMock()
    snap.state.affect.render.return_value = "calm"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""

    persona_block = collect_persona_injected(persona_snap=persona_snap)
    status_block = collect_status_injected(presence_snap=snap)

    assert persona_block.traits
    assert "calm" not in persona_block.traits
    assert "A" not in status_block.presence
