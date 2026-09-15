"""speak.performance — 旁路表演管线（L2 表演层的新设计落点）。

storybus 新设计过程下 speak 侧的剧情表演通路，与旧 request_driven 机器
（directors/screenwriter/story_pool，供能已拆除）并行存在、互不供血：

    life beat（storybus）→ BeatPerformer（开口决策 → 帧闸 → 表演端口）
                          → 逐渠道 BeatAck 回 life

- ``policy``     开口决策（BeatOpeningPolicy / FrameGate，自 character 迁入）；
- ``buffer``     角色记忆缓冲（占位，自 character 迁入）；
- ``performer``  旁路管线引擎（决策与表演收拢，wiring 桥退位为投递适配）。

交互账本与节奏阶梯（R7 深水区）仍留旧管线，迁移另行批次。
"""
from __future__ import annotations

from .buffer import CharacterMemoryBuffer
from .performer import BeatPerformer
from .policy import (
    HOLD,
    PERFORM_NOW,
    SILENCE,
    BeatOpeningPolicy,
    FrameGate,
    OpeningDecision,
)

__all__ = [
    "HOLD",
    "PERFORM_NOW",
    "SILENCE",
    "BeatOpeningPolicy",
    "BeatPerformer",
    "CharacterMemoryBuffer",
    "FrameGate",
    "OpeningDecision",
]
