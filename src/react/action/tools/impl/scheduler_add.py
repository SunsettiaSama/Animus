from __future__ import annotations

from typing import Any, ClassVar
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class SchedulerAddArgs(BaseModel):
    name: str = Field(..., min_length=1, description="任务名称，便于识别")
    instruction: str = Field(..., min_length=1, description="到时间后发给 Agent 的指令内容")
    trigger_type: str = Field(
        "once",
        description="触发类型：once（一次性，需填 at）| interval（周期性，需填 interval_seconds）",
    )
    at: str = Field(
        "",
        description="触发时间，ISO8601 格式（如 2026-04-29T17:00:00），trigger_type=once 时必填",
    )
    interval_seconds: int = Field(
        0,
        ge=0,
        description="周期间隔（秒），trigger_type=interval 时必填，如 1800 = 每30分钟",
    )
    profile: str = Field(
        "minimal",
        description="执行配置：minimal（仅LLM+工具）| with_memory（开启长期记忆）| full（记忆+人格）",
    )


class SchedulerAddAction(BaseAction):
    name: str = "scheduler_add"
    description: str = (
        "在时间轴上预约一个 Agent 任务。支持一次性触发（once）和周期性触发（interval）。"
        "参数：name（任务名），instruction（到时发给 Agent 的指令），"
        "trigger_type（once|interval），at（ISO8601 时间，once 时必填），"
        "interval_seconds（间隔秒数，interval 时必填），"
        "profile（minimal|with_memory|full，默认 minimal）。"
        "返回 task_id 和下次触发时间。"
    )
    args_model: ClassVar[type[BaseModel]] = SchedulerAddArgs

    engine: Any = None  # SchedulerEngine，构造时注入

    def execute(
        self,
        name: str,
        instruction: str,
        trigger_type: str = "once",
        at: str = "",
        interval_seconds: int = 0,
        profile: str = "minimal",
        **kwargs,
    ) -> str:
        if self.engine is None:
            return "调度器未初始化。"

        if trigger_type == "once":
            if not at:
                return "trigger_type=once 时必须提供 at 参数（ISO8601 格式）。"
            try:
                at_dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                if at_dt.tzinfo is None:
                    at_dt = at_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return f"at 参数格式无效，请使用 ISO8601（如 2026-04-29T17:00:00）：{at}"
            task = self.engine.schedule_once(name, instruction, at_dt, profile)
            return (
                f"已预约一次性任务。\n"
                f"task_id: {task.id}\n"
                f"名称: {task.name}\n"
                f"触发时间: {task.next_run_at}\n"
                f"执行配置: {profile}"
            )

        if trigger_type == "interval":
            if interval_seconds <= 0:
                return "trigger_type=interval 时 interval_seconds 必须 > 0。"
            task = self.engine.schedule_interval(name, instruction, interval_seconds, profile)
            return (
                f"已预约周期性任务。\n"
                f"task_id: {task.id}\n"
                f"名称: {task.name}\n"
                f"首次触发: {task.next_run_at}\n"
                f"间隔: 每 {interval_seconds} 秒\n"
                f"执行配置: {profile}"
            )

        return f"未知 trigger_type：{trigger_type!r}，请使用 once 或 interval。"
