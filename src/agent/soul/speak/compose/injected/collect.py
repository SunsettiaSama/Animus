from __future__ import annotations

from .context import SpeakInjectedContext
from .persona import collect_persona_injected
from agent.soul.speak.io.inbound.compose import collect_status_injected


def collect_injected(
    *,
    persona_snap: dict,
    presence_snap,
    user_text: str,
    dialogue_compressed: str = "",
    max_profile_chars: int = 1200,
    max_concept_chars: int = 800,
    max_presence_chars: int = 600,
    status_store=None,
) -> SpeakInjectedContext:
    """分别采集人格层与状态层，再组装为 Speak 外部注入上下文。"""
    return SpeakInjectedContext(
        persona=collect_persona_injected(
            persona_snap=persona_snap,
            max_profile_chars=max_profile_chars,
            max_concept_chars=max_concept_chars,
        ),
        status=collect_status_injected(
            presence_snap=presence_snap,
            dialogue_compressed=dialogue_compressed,
            max_presence_chars=max_presence_chars,
            status_store=status_store,
        ),
        user_text=user_text.strip(),
    )
