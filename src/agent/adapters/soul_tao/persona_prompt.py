from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from .blocks import PresenceBlock, PresenceSelfNarrativeBlock
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
    snap = soul.query_persona(session_id=session_id)
    blocks = blocks_from_persona_snapshot(snap, max_profile_chars=max_profile_chars)
    self_narrative = str(snap.get("presence_self_narrative", "")).strip()
    if self_narrative:
        blocks.append(PresenceSelfNarrativeBlock(self_narrative, max_chars=max_affect_chars))
    affect = snap.get("presence_affect") or {}
    presence_raw = snap.get("presence") or {}
    if presence_raw:
        from agent.soul.presence.state import PresenceState

        state = PresenceState.from_dict(presence_raw)
        if not state.is_empty():
            blocks.append(PresenceBlock(state, max_chars=max_affect_chars))
    elif affect:
        from agent.soul.presence.state.static import AffectState

        state = PresenceState(affect=AffectState.from_dict(affect))
        if not state.is_empty():
            blocks.append(PresenceBlock(state, max_chars=max_affect_chars))
    return blocks
