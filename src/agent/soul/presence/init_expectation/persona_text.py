from __future__ import annotations

from typing import Any

from agent.soul.persona.profile.profile import PersonaProfile


def persona_text_from_snapshot(snapshot: dict[str, Any]) -> str:
    profile = snapshot.get("profile") or {}
    if isinstance(profile, PersonaProfile):
        parts = [_profile_chunks(profile)]
    elif isinstance(profile, dict):
        parts = [_profile_chunks(PersonaProfile.from_dict(profile))]
    else:
        parts = []

    concept = snapshot.get("self_concept") or {}
    if isinstance(concept, dict):
        for key in ("identity", "narrative", "growth_arc", "relational_stance"):
            value = str(concept.get(key, "")).strip()
            if value:
                parts.append(value)
        traits = concept.get("traits") or []
        if isinstance(traits, list):
            parts.extend(str(t).strip() for t in traits if str(t).strip())

    keywords = snapshot.get("attention_keywords") or []
    if isinstance(keywords, list):
        parts.extend(str(k).strip() for k in keywords if str(k).strip())

    return "\n".join(p for p in parts if p).strip()


def _profile_chunks(profile: PersonaProfile) -> str:
    lines: list[str] = []
    if profile.name.strip():
        lines.append(profile.name.strip())
    lines.extend(profile.core_traits)
    if profile.interpersonal_style.strip():
        lines.append(profile.interpersonal_style.strip())
    if profile.emotional_expressiveness.strip():
        lines.append(profile.emotional_expressiveness.strip())
    if profile.core_motivation.strip():
        lines.append(profile.core_motivation.strip())
    lines.extend(profile.background_facts)
    lines.extend(profile.values)
    return "\n".join(lines)
