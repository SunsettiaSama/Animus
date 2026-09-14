"""storybus — life ↔ speak 剧情通信契约内核（L0，零实现零依赖）。

分层契约（docs/product/single-stream-dialogue-requirements.md §5）：
- 本包只放消息数据类与端口 Protocol，**禁止 import 任何 soul 子系统实现**；
- life/story（L1）实现 Outbox 侧，speak（L2）实现 Inbox 侧；
- 进程内总线的具体实现放 ``agent/soul/wiring/story.py``（L3 组装层）。

四类消息（协议 v1.2）：
- ``LifeStoryBeat``    life → speak：给角色的"想说的话"（建议性 hint，开口时机角色自决）
- ``StoryProgressSync`` life → speak：剧情卡片进度段刷新（无 ack，可丢可合并）
- ``StorySignal``      speak → life：用户轮信号（供导演做缓存失效判定）
- ``BeatAck``          speak/角色 → life：演出回执（五态）
"""
from __future__ import annotations

from .messages import (
    BeatAck,
    BeatAckStatus,
    BeatDraft,
    BeatProvenance,
    LifeStoryBeat,
    PerformanceHint,
    StoryCard,
    StoryProgressSync,
    StorySignal,
)
from .ports import (
    BeatAckReceiver,
    LifeStoryOutboxPort,
    SpeakBeatInboxPort,
    StorySignalInbox,
)

__all__ = [
    "BeatAck",
    "BeatAckStatus",
    "BeatDraft",
    "BeatProvenance",
    "LifeStoryBeat",
    "PerformanceHint",
    "StoryCard",
    "StoryProgressSync",
    "StorySignal",
    "BeatAckReceiver",
    "LifeStoryOutboxPort",
    "SpeakBeatInboxPort",
    "StorySignalInbox",
]
