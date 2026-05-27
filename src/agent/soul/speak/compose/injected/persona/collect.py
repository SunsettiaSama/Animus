from __future__ import annotations

from .block import SpeakPersonaInjected
from .render import render_self_concept, render_traits


def collect_persona_injected(
    *,
    persona_snap: dict,
    max_profile_chars: int = 1200,
    max_concept_chars: int = 800,
) -> SpeakPersonaInjected:
    """从 persona 快照采集稳定人格层（不读 presence / 对话状态）。"""
    return SpeakPersonaInjected(
        traits=render_traits(persona_snap, max_chars=max_profile_chars),
        self_concept=render_self_concept(persona_snap, max_chars=max_concept_chars),
    )
