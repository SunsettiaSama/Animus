from __future__ import annotations

from agent.soul.persona.distill.schema import PERSONA_DISTILL_SCHEMA_VERSION

_DEFAULT_DIALOGUE = (
    "你是莉奈娅，边境探险队的同行者与记录者。你说话不急，习惯先听清对方再开口；"
    "语气平稳、偏亲近，少花哨，关键处才稍微加重。你不爱说教，没把握时会先确认事实。"
)


def persona_snapshot_with_distill(
    *,
    dialogue: str = _DEFAULT_DIALOGUE,
    name: str = "A",
    source_revision: str = "test|",
) -> dict:
    return {
        "profile": {"name": name, "core_traits": ["calm"], "built": True, "built_at": "test"},
        "self_concept": {"narrative": "I accompany the user.", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": PERSONA_DISTILL_SCHEMA_VERSION,
            "source_revision": source_revision,
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "slices": {
                "general": f"{name}：冷静、克制",
                "dialogue": dialogue,
                "story": "背景待续",
                "reasoning": "先框架后细节",
                "memory_anchor": "你是冷静陪伴者，习惯把对话整理成可回顾的线索。",
            },
        },
    }
