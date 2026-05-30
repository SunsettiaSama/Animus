from __future__ import annotations

from typing import Any


def build_agent_persona_narrative(snap: dict[str, Any]) -> str:
    """供 memory 归档 / life 虚拟叙事使用的 Agent 人格正文（非 Speak 注入格式）。"""
    from agent.soul.speak.compose.injected.persona.render import (
        render_self_concept,
        render_traits,
    )

    parts: list[str] = []
    traits = render_traits(snap, max_chars=1200).strip()
    if traits:
        parts.append(traits)
    concept = render_self_concept(snap, max_chars=800).strip()
    if concept:
        parts.append(concept)
    return "\n\n".join(parts)
