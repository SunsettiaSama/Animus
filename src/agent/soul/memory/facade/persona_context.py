from __future__ import annotations

from typing import Any


def build_agent_persona_narrative(snap: dict[str, Any]) -> str:
    """供 memory 归档 / life 虚拟叙事使用的 Agent 人格正文（主画像，非 Speak）。"""
    from agent.soul.persona.render_voice import (
        render_main_profile_from_snap,
        render_self_concept_from_snap,
    )

    parts: list[str] = []
    traits = render_main_profile_from_snap(
        snap,
        max_chars=1200,
        caller="build_agent_persona_narrative",
    )
    if traits:
        parts.append(traits)
    concept = render_self_concept_from_snap(
        snap,
        max_chars=800,
        caller="build_agent_persona_narrative",
    )
    if concept:
        parts.append(concept)
    return "\n\n".join(parts)
