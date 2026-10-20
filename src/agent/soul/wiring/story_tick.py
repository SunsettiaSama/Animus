# -*- coding: utf-8 -*-
"""story 心跳入口：剧情帧 tick + 演化过道（R6.1 常驻化，与前端在否无关）。"""

from __future__ import annotations

from typing import Any

from agent.soul.heartbeat.schedule.context import HeartbeatContext
from agent.soul.heartbeat.schedule.item import ChecklistItem, ChecklistTrigger


def story_wake_items() -> list[ChecklistItem]:
    return [
        ChecklistItem(
            id="story-tick",
            domain="story",
            action="story.tick",
            trigger=ChecklistTrigger.interval,
            interval_sec=300.0,
            target="agent.soul.wiring.story_tick:story_tick_entry",
        ),
    ]


def story_tick_entry(payload: dict, ctx: HeartbeatContext) -> Any:
    """帧内轻账目 + 有容量时把演化过道作为重任务提交给心跳 worker。"""
    _ = payload
    from agent.soul.wiring.story import ensure_story_runtime

    runtime = ensure_story_runtime(ctx.soul)
    result = runtime.tick()
    runtime.maybe_submit_evolve(ctx.orchestrator)
    return result


def story_evolve_entry(payload: dict, ctx: HeartbeatContext) -> Any:
    """一次性重任务（submit_heavy 提交，id=story-evolve）：地标提前演化 + echo 补稿。"""
    _ = payload
    from agent.soul.wiring.story import ensure_story_runtime

    ensure_story_runtime(ctx.soul).evolve_pass()
    return {"evolve": "done"}
