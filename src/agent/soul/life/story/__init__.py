"""life.story — 剧情子域（L1）：导演/编剧/卡片的常驻家（自 speak 迁入，R6）。

分层契约：依赖 storybus 契约与 life 内部件；**禁止 import speak / webui**。
物理迁移（directors/screenwriter/pool 自 speak/request_driven 搬入）按需求
Phase 4 执行；本包先行承接 outbox / 账本 / 排程器。
"""
from __future__ import annotations

from .cards import StoryCardStore
from .outbox import BeatLedger, StoryOutbox
from .scheduler import BeatSource, CallableBeatSource, StoryAction, StoryScheduler

__all__ = [
    "BeatLedger",
    "StoryOutbox",
    "BeatSource",
    "CallableBeatSource",
    "StoryAction",
    "StoryScheduler",
    "StoryCardStore",
]
