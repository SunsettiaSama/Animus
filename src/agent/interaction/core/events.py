from __future__ import annotations

from dataclasses import dataclass

from .semantic import SemanticInteraction


@dataclass(frozen=True)
class InteractionClosedEvent:
    """SemanticInteraction 闭合事件 — 供 anchor 等下游订阅，交互层不依赖消费者。"""

    interaction: SemanticInteraction
