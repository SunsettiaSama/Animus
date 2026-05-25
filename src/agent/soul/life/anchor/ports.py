"""锚点层 ↔ 编排器 接口约定（re-export）。"""

from agent.soul.presence.experience.anchor_codec import (
    AnchorUnitContext,
    InteractionDirection,
    read_anchor_context,
    stamp_anchor_context,
)

__all__ = [
    "AnchorUnitContext",
    "InteractionDirection",
    "read_anchor_context",
    "stamp_anchor_context",
]
