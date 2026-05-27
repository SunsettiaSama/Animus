from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.compose.injected import (
    collect_persona_injected,
    collect_status_injected,
)


def test_persona_collect_only_reads_persona_snapshot():
    persona_snap = {
        "profile": {"name": "小A", "core_traits": ["温和"]},
        "self_concept": {"narrative": "我在陪伴用户。"},
    }
    injected = collect_persona_injected(persona_snap=persona_snap)
    assert "小A" in injected.traits
    assert "陪伴用户" in injected.self_concept


def test_status_collect_only_reads_presence_and_dialogue():
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "专注"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    presence.snapshot.return_value = snap

    injected = collect_status_injected(
        presence_snap=snap,
        dialogue_compressed="【当前对话·压缩】\n- 用户聊了架构",
    )
    assert "专注" in injected.presence
    assert "架构" in injected.dialogue_compressed
    assert "小A" not in injected.presence


def test_persona_and_status_blocks_do_not_cross():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {
        "profile": {"name": "小A"},
        "self_concept": {},
    }
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "平静"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    presence.snapshot.return_value = snap

    persona_block = collect_persona_injected(persona_snap=persona.get_persona_snapshot())
    status_block = collect_status_injected(presence_snap=snap)

    assert persona_block.traits
    assert "平静" not in persona_block.traits
    assert "小A" not in status_block.presence
