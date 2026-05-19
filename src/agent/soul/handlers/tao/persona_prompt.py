from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from agent.soul.persona.profile.block import ProfileBlock
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.block import SelfConceptBlock
from agent.soul.persona.self_concept.concept import SelfConcept
from agent.soul.persona.status.block import StatusBlock
from agent.soul.persona.status.emotional import EmotionalState


def blocks_from_persona_snapshot(
    snap: dict,
    *,
    max_profile_chars: int = 500,
    max_status_chars: int = 600,
) -> list[PromptBlock]:
    """将 Soul.query_persona() 快照展开为 prompt 注入块。"""
    blocks: list[PromptBlock] = []

    profile_raw = snap.get("profile") or {}
    if profile_raw:
        profile = PersonaProfile.from_dict(profile_raw)
        blocks.append(ProfileBlock(profile, max_chars=max_profile_chars))

    concept_raw = snap.get("self_concept") or {}
    concept = SelfConcept.from_dict(concept_raw)
    if not concept.is_empty():
        blocks.append(SelfConceptBlock(concept))

    status_raw = snap.get("status") or {}
    if status_raw:
        emotional = EmotionalState.from_dict(status_raw)
        if not emotional.is_empty():
            blocks.append(StatusBlock(emotional, max_chars=max_status_chars))

    return blocks


def blocks_from_soul_query(
    soul,
    *,
    max_profile_chars: int = 500,
    max_status_chars: int = 600,
) -> list[PromptBlock]:
    """从 Soul 拉取完整人格快照并展开为 prompt 块。"""
    snap = soul.query_persona()
    return blocks_from_persona_snapshot(
        snap,
        max_profile_chars=max_profile_chars,
        max_status_chars=max_status_chars,
    )
