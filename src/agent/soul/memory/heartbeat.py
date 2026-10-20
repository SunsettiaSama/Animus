# -*- coding: utf-8 -*-
"""memory 域心跳入口：wander / forget scan / sleep 的唤醒实现与注册项。

契约：``target(payload: dict, ctx: HeartbeatContext) -> dict``；
实现知识住在 memory 域，heartbeat 零模块知识（wake-registration-prd）。
"""

from __future__ import annotations

import uuid
from typing import Any

from agent.soul.evolution_capture import EvolutionCapture, beats_from_dicts
from agent.soul.heartbeat.schedule.context import HeartbeatContext
from agent.soul.heartbeat.schedule.item import ChecklistItem, ChecklistTrigger
from agent.soul.handlers.api.actions import MemoryAction


def _resolve_memory_sleep_at(cfg) -> str:
    hb = getattr(cfg, "heartbeat", None)
    if hb is not None:
        at = getattr(hb, "memory_sleep_at", None)
        if at:
            return str(at)
    at = getattr(cfg, "memory_sleep_at", None)
    if at:
        return str(at)
    return "04:00"


def wake_items(cfg) -> list[ChecklistItem]:
    c = cfg or _fallback_cfg()
    return [
        ChecklistItem(
            id="memory-wander",
            domain="memory",
            action=MemoryAction.WANDER,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.wander_interval_sec,
            target="agent.soul.memory.heartbeat:run_wander_entry",
            heavy=True,
        ),
        ChecklistItem(
            id="memory-forget",
            domain="memory",
            action=MemoryAction.FORGET_SCAN,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.memory_forget_interval_sec,
            target="agent.soul.memory.heartbeat:run_forget_scan_entry",
            heavy=True,
        ),
        ChecklistItem(
            id="memory-sleep",
            domain="memory",
            action=MemoryAction.SLEEP,
            trigger=ChecklistTrigger.daily,
            daily_at=_resolve_memory_sleep_at(c),
            target="agent.soul.memory.heartbeat:run_memory_sleep_entry",
            heavy=True,
            run_outside_active_hours=True,
        ),
    ]


def _fallback_cfg():
    from config.soul.config import SoulConfig

    return SoulConfig.default()


def run_wander_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    """wander + 演化捕获 + 剧情侧结果塑形。"""
    soul = ctx.soul
    result, story_beats = soul.run_wander()
    capture_report = EvolutionCapture.after_wander(
        soul,
        result,
        beats_from_dicts(story_beats),
    )
    return {
        "tick_id": result.tick_id,
        "wandered": len(result.wandered_ids),
        "ruminated": len(result.ruminated_ids),
        "intensity": result.signal.intensity,
        "dominant_emotion": result.signal.dominant_emotion,
        "flushed": result.forgotten_count,
        "forgotten": result.forgotten_count,
        "narrative_triggered": result.narrative_triggered,
        "story_beats": len(story_beats),
        "buffer_signals": len(result.buffer_candidates),
        "capture_events": len(capture_report.events),
        "capture_outbound": capture_report.outbound_count,
        "rumination_fsm": capture_report.rumination_count,
    }


def run_forget_scan_entry(payload: dict, ctx: HeartbeatContext) -> Any:
    from agent.soul.request import SoulChannel, SoulDomain, SoulRequest

    return ctx.soul.dispatch(SoulRequest(
        domain=SoulDomain.memory,
        action=MemoryAction.FORGET_SCAN,
        payload=dict(payload),
        channel=SoulChannel.api,
    ))


def run_memory_sleep_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    return ctx.soul.run_memory_sleep(dry_run=bool(payload.get("dry_run", False)))


def new_heartbeat_tick_id() -> str:
    """演化 tick 的唯一标识（wander / memory sleep 共用）。"""
    return str(uuid.uuid4())
