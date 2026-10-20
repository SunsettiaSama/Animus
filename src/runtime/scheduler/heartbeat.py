# -*- coding: utf-8 -*-
"""scheduler 域心跳入口：每日 planner/review 预约的存在性保证。

两个内置 cron（08:00 规划 / 22:00 复盘，LLM 经 TaskRunner 执行，含重试
与长期记忆写入）此前从未被激活。心跳每个周期幂等确保它们注册在 engine
时间轴上：engine 未绑定/重启后，最多一个心跳周期内自动补注册；
执行仍由 engine 时钟负责（复用既有任务基建）。
"""

from __future__ import annotations

from typing import Any

from agent.soul.heartbeat.schedule.context import HeartbeatContext
from agent.soul.heartbeat.schedule.item import ChecklistItem, ChecklistTrigger


def wake_items() -> list[ChecklistItem]:
    return [
        ChecklistItem(
            id="scheduler-daily-planner-review-ensure",
            domain="scheduler",
            action="daily-planner-review.ensure",
            trigger=ChecklistTrigger.interval,
            interval_sec=3600.0,
            target="runtime.scheduler.heartbeat:ensure_daily_agents_entry",
        ),
    ]


def ensure_daily_agents_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    engine = ctx.scheduler_engine
    if engine is None:
        return {"skipped": "no scheduler engine"}
    engine.schedule_daily_planner(hour=int(payload.get("planner_hour", 8)))
    engine.schedule_daily_review(hour=int(payload.get("review_hour", 22)))
    return {"ensured": True}
