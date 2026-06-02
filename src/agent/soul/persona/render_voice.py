"""主画像 / 自叙：面向角色 LLM 的渲染（非 Speak 子画像）。"""

from __future__ import annotations

from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import SelfConcept


def _trunc(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text.strip()
    return text[:max_chars].rstrip()


def render_main_profile_from_snap(
    snap: dict,
    *,
    max_chars: int = 1200,
    caller: str = "render_main_profile_from_snap",
) -> str:
    profile_raw = snap.get("profile") or {}
    if not profile_raw:
        return ""
    profile = PersonaProfile.from_dict(profile_raw)
    return _trunc(
        profile.render(warn_main_portrait=True, caller=caller),
        max_chars,
    )


def render_self_concept_from_snap(
    snap: dict,
    *,
    max_chars: int = 800,
    caller: str = "render_self_concept_from_snap",
) -> str:
    concept_raw = snap.get("self_concept") or {}
    concept = SelfConcept.from_dict(concept_raw)
    if concept.is_empty():
        return ""
    return _trunc(
        concept.render_for_role_llm(warn_main_portrait=True, caller=caller),
        max_chars,
    )
