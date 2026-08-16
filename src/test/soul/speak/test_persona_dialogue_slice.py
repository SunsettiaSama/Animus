from __future__ import annotations

from agent.soul.memory.facade.persona_context import (
    build_agent_persona_narrative,
    build_speak_dialogue_persona_anchor,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.persona.runtime.identity.collect import (
    collect_stable_portrait,
)


def test_speak_persona_anchor_uses_dialogue_slice_only():
    snap = {
        "profile": {
            "name": "莉奈娅",
            "background_facts": ["主画像事实不应进入 Speak"],
            "core_traits": ["博物学家"],
        },
        "self_concept": {
            "narrative": "主画像自我认知不应进入 Speak",
            "beliefs": [],
        },
        "persona_distill": {
            "slices": {
                "general": "你是莉奈娅，一位博物学家……",
                "dialogue": "你是莉奈娅，跟人说话时习惯先露出轻快的笑。",
            }
        },
    }
    anchor = build_speak_dialogue_persona_anchor(snap)
    assert "轻快的笑" in anchor
    assert "主画像事实" not in anchor
    assert "主画像自我认知" not in anchor


def test_collect_stable_portrait_prefers_dialogue_over_general():
    snap = {
        "persona_distill": {
            "slices": {
                "general": "GENERAL_ONLY",
                "dialogue": "DIALOGUE_SLICE",
            }
        }
    }
    assert collect_stable_portrait(persona_snap=snap) == "DIALOGUE_SLICE"


def test_collect_stable_portrait_falls_back_to_general():
    snap = {
        "persona_distill": {
            "slices": {
                "general": "GENERAL_ONLY",
                "dialogue": "",
            }
        }
    }
    assert collect_stable_portrait(persona_snap=snap) == "GENERAL_ONLY"


def test_memory_persona_narrative_still_uses_main_portrait():
    snap = {
        "profile": {
            "name": "莉奈娅",
            "background_facts": ["事实背景"],
            "core_traits": ["好奇"],
        },
        "self_concept": {
            "narrative": "自我认知正文",
            "beliefs": [],
        },
        "persona_distill": {
            "slices": {"dialogue": "对话切片不应出现在 Memory 主画像"}
        },
    }
    narrative = build_agent_persona_narrative(snap)
    assert "事实背景" in narrative or "好奇" in narrative or "莉奈娅" in narrative
    assert "对话切片不应出现在 Memory 主画像" not in narrative
