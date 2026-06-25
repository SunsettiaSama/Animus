"""Persona 子块出站渲染与 legacy guard。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .layer import SpeakPersonaLayer

_SPEAK_PERSONA_FORBIDDEN = (
    "Speak 不得注入主画像（built_profile / self_concept）。"
    "请使用 PersonaComposeService 读取 persona_distill.slices.general + presence 自叙。"
)


def render_persona_blocks(layer: SpeakPersonaLayer) -> list[str]:
    """按 identity → presence 顺序渲染（静态人格层）。"""
    return [
        block.strip()
        for block in (
            layer.identity.render(),
            layer.presence.render(),
        )
        if block.strip()
    ]


def render_self_narrative_block(text: str) -> str:
    from .blocks.identity import PersonaIdentityBlock

    return PersonaIdentityBlock(narrative=text).render()


def render_traits(*args, **kwargs) -> str:
    raise RuntimeError(_SPEAK_PERSONA_FORBIDDEN)


def render_self_concept(*args, **kwargs) -> str:
    raise RuntimeError(_SPEAK_PERSONA_FORBIDDEN)


render_persona_traits = render_traits
render_self_concept_full = render_self_concept
