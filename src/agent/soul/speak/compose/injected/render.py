from __future__ import annotations


def truncate_text(text: str, max_chars: int) -> str:
    normalized = text.strip()
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars]


def render_persona_traits(
    snap: dict,
    *,
    max_chars: int = 1200,
) -> str:
    """Persona 稳定特质层：完整 PersonaProfile。"""
    from agent.soul.persona.profile.profile import PersonaProfile

    profile_raw = snap.get("profile") or {}
    if not profile_raw:
        return ""
    profile = PersonaProfile.from_dict(profile_raw)
    return truncate_text(profile.render(), max_chars)


def render_self_concept_full(
    snap: dict,
    *,
    max_chars: int = 800,
) -> str:
    """Persona self_concept 层：叙事 + 全部信念。"""
    from agent.soul.persona.self_concept.concept import BeliefStrength, SelfConcept

    concept_raw = snap.get("self_concept") or {}
    concept = SelfConcept.from_dict(concept_raw)
    if concept.is_empty():
        return ""

    parts: list[str] = ["【自我认知】"]
    if concept.narrative:
        parts.append(concept.narrative)

    grouped: dict[str, list[str]] = {
        BeliefStrength.core.value: [],
        BeliefStrength.established.value: [],
        BeliefStrength.emerging.value: [],
    }
    for belief in concept.beliefs:
        grouped[belief.strength.value].append(belief.content.strip())

    if grouped[BeliefStrength.core.value]:
        parts.append("核心信念：")
        parts.extend(f"- {text}" for text in grouped[BeliefStrength.core.value] if text)
    if grouped[BeliefStrength.established.value]:
        parts.append("已确立信念：")
        parts.extend(f"- {text}" for text in grouped[BeliefStrength.established.value] if text)
    if grouped[BeliefStrength.emerging.value]:
        parts.append("新兴信念：")
        parts.extend(f"- {text}" for text in grouped[BeliefStrength.emerging.value] if text)

    return truncate_text("\n".join(parts), max_chars)


def render_presence_static(state, *, max_chars: int = 600) -> str:
    """Presence 静态层：affect / somatic / cognition / perception（不含 expectation）。"""
    if state is None:
        return ""

    labels = (
        ("affect", "情感"),
        ("somatic", "身体"),
        ("cognition", "认知"),
        ("perception", "感知"),
    )
    lines: list[str] = ["【当下态·静态】"]
    for key, label in labels:
        text = getattr(state, key).render()
        if text:
            lines.append(f"{label}：{text}")
    if len(lines) == 1:
        return ""
    return truncate_text("\n".join(lines), max_chars)
