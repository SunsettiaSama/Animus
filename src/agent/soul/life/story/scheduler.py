"""life.story.scheduler — 剧情排程器：heartbeat tick → beat 生产。

挂载方式（R6.1 常驻化）：注册为 heartbeat checklist item（domain="story"），
orchestrator 每 tick 调用 ``StoryScheduler.tick()``；与前端在否无关。

BeatSource（R6.2 剧情驱动）是剧情供给口，后续由导演/编剧（自 speak 迁入）实现；
当前提供 CallableBeatSource 供 wiring 注入与测试使用。
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from agent.soul.storybus import BeatDraft

logger = logging.getLogger(__name__)


class StoryAction:
    """checklist action 常量（domain = "story"）。"""

    TICK = "story.tick"


class BeatSource(Protocol):
    """剧情供给口：到期该投递的 beat 草稿。"""

    def due_beats(self, now: float) -> list[BeatDraft]:
        ...


class CallableBeatSource:
    """以函数为供给源的适配器（wiring / 测试用）。"""

    def __init__(self, fn: Callable[[float], list[BeatDraft]] | None = None) -> None:
        self._fn = fn or (lambda now: [])

    def due_beats(self, now: float) -> list[BeatDraft]:
        try:
            return list(self._fn(now) or [])
        except Exception:  # noqa: BLE001 — 供给源故障不拖垮心跳
            logger.exception("[story.scheduler] beat source failed")
            return []


class StoryScheduler:
    """tick 驱动的剧情排程：source → outbox。"""

    def __init__(self, outbox, source: BeatSource, *, clock: Callable[[], float] = time.time) -> None:
        self._outbox = outbox
        self._source = source
        self._clock = clock
        self._emitted_total = 0

    def tick(self) -> dict:
        now = self._clock()
        emitted = 0
        for draft in self._source.due_beats(now):
            beat = self._outbox.emit(draft)
            if beat is not None:
                emitted += 1
                self._emitted_total += 1
                logger.info(
                    "[story.scheduler] beat emitted id=%s kind=%s channels=%s",
                    beat.beat_id, beat.kind, ",".join(beat.channels) or "-",
                )
        return {"emitted": emitted, "total": self._emitted_total}
