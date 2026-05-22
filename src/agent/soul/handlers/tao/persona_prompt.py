from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from agent.soul.presence.block import PresenceAffectBlock
from agent.soul.persona.profile.block import ProfileBlock
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.block import SelfConceptBlock
from agent.soul.persona.self_concept.concept import SelfConcept


def blocks_from_persona_snapshot(
    snap: dict,
    *,
    max_profile_chars: int = 500,
) -> list[PromptBlock]:
    blocks: list[PromptBlock] = []

    profile_raw = snap.get("profile") or {}
    if profile_raw:
        profile = PersonaProfile.from_dict(profile_raw)
        blocks.append(ProfileBlock(profile, max_chars=max_profile_chars))

    concept_raw = snap.get("self_concept") or {}
    concept = SelfConcept.from_dict(concept_raw)
    if not concept.is_empty():
        blocks.append(SelfConceptBlock(concept))

    return blocks


def blocks_from_soul_query(
    soul,
    *,
    max_profile_chars: int = 500,
    max_affect_chars: int = 600,
    session_id: str = "tao",
) -> list[PromptBlock]:
    snap = soul.query_persona()
    blocks = blocks_from_persona_snapshot(snap, max_profile_chars=max_profile_chars)
    affect = snap.get("presence_affect") or {}
    if affect:
        from agent.soul.presence.affect import AffectState

        state = AffectState.from_dict(affect)
        if not state.is_empty():
            blocks.append(PresenceAffectBlock(state, max_chars=max_affect_chars))
    return blocks
