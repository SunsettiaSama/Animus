from __future__ import annotations

from typing import TYPE_CHECKING

from .compose.state import PersonaComposeState
from .limits import STABLE_HARD_MAX_CHARS
from .identity.collect import collect_stable_portrait
from .layer import SpeakPersonaLayer
from .narrative.distill import distill_self_narrative
from .presence.collect import collect_state_portrait

if TYPE_CHECKING:
    from agent.soul.speak.io.inbound.compose.store import SpeakStatusStore


def collect_persona_layer(
    *,
    persona_snap: dict,
    presence_snap=None,
    dialogue_compressed: str = "",
    max_dialogue_chars: int = STABLE_HARD_MAX_CHARS,
    max_presence_chars: int = 350,
    status_store: SpeakStatusStore | None = None,
    llm=None,
) -> SpeakPersonaLayer:
    """同步采集人格层（测试 / fallback）：identity + presence → narrative。"""
    _ = max_dialogue_chars
    stable = collect_stable_portrait(
        persona_snap=persona_snap,
        max_chars=max_dialogue_chars,
    )
    state_text = ""
    if presence_snap is not None:
        state_text = collect_state_portrait(
            presence_snap=presence_snap,
            max_presence_chars=max_presence_chars,
            status_store=status_store,
        )
    narrative = distill_self_narrative(
        llm,
        stable_portrait=stable,
        state_portrait=state_text,
    )
    composed = PersonaComposeState(
        self_narrative=narrative,
        stable_portrait=stable,
        state_portrait=state_text,
        version=1,
    )
    layer = SpeakPersonaLayer.from_compose(composed)
    layer.dialogue_compressed = dialogue_compressed.strip()
    return layer


def collect_persona_distill(
    *,
    persona_snap: dict,
    max_dialogue_chars: int = STABLE_HARD_MAX_CHARS,
) -> str:
    return collect_stable_portrait(
        persona_snap=persona_snap,
        max_chars=max_dialogue_chars,
    )
