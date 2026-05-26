from __future__ import annotations

from .context import SpeakInjectedContext
from .render import render_persona_traits, render_presence_static, render_self_concept_full


def collect_injected(
    *,
    persona_snap: dict,
    presence_snap,
    user_text: str,
    max_profile_chars: int = 1200,
    max_concept_chars: int = 800,
    max_presence_chars: int = 600,
) -> SpeakInjectedContext:
    """从 persona / presence 快照收集外部注入上下文。"""
    return SpeakInjectedContext(
        persona_traits=render_persona_traits(
            persona_snap,
            max_chars=max_profile_chars,
        ),
        self_concept=render_self_concept_full(
            persona_snap,
            max_chars=max_concept_chars,
        ),
        presence_static=render_presence_static(
            presence_snap.state,
            max_chars=max_presence_chars,
        ),
        user_text=user_text.strip(),
    )
