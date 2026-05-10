from __future__ import annotations

from typing import Any, ClassVar
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class SchedulerAddArgs(BaseModel):
    name: str = Field(..., min_length=1, description="任务名称，便于识别")
    instruction: str = Field(..., min_length=1, description="到时间后发给 Agent 的指令内容")
    trigger_type: str = Field(
        "once",
        description=(
            "触发类型：once（一次性，需填 at）| interval（周期性，需填 interval_seconds）"
            "| cron（Cron 表达式，需填 cron_expr，如 '0 8 * * *' 表示每天早8点）"
        ),
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
    cron_expr: str = Field(
        "",
        description="Cron 表达式，trigger_type=cron 时必填，如 '0 8 * * *'（每天早8点）",
    )
    profile: str = Field(
        "minimal",
        description="执行配置：minimal（仅LLM+工具）| with_memory（开启长期记忆）| full（记忆+人格）",
    )
    delivery: str = Field(
        "push",
        description=(
            "结果投递方式：push（完成后推送通知，默认）| silent（只存结果，不推送，适合任务链中间步骤）"
            "| store_only（写入长期记忆，不推送）"
        ),
    )
    on_complete: str = Field(
        "",
        description=(
            "任务链：本任务完成后立即触发的下一个指令模板，支持 {result} 占位符引用本次结果。"
            "留空表示无后续任务。"
        ),
    )
    max_retries: int = Field(
        0,
        ge=0,
        description="失败后最大重试次数，0 表示不重试",
    )


class SchedulerAddAction(BaseAction):
    name: str = "scheduler_add"
    description: str = (
        "在时间轴上预约一个 Agent 任务。支持一次性（once）、周期性（interval）、Cron 表达式（cron）三种触发方式。"
        "参数：name（任务名），instruction（到时发给 Agent 的指令），trigger_type，"
        "at（ISO8601，once 时必填），interval_seconds（interval 时必填），cron_expr（cron 时必填），"
        "profile（minimal|with_memory|full），delivery（push|silent|store_only），"
        "on_complete（任务链下一步指令模板，支持 {result}），max_retries（失败重试次数）。"
        "返回 task_id 和下次触发时间。"
    )
    args_model: ClassVar[type[BaseModel]] = SchedulerAddArgs

    engine: Any = None        # SchedulerEngine，构造时注入
    reply_target: Any = None  # dict | None，构造时注入，持久化到任务中

    def execute(
        self,
        name: str,
        instruction: str,
        trigger_type: str = "once",
        at: str = "",
        interval_seconds: int = 0,
        cron_expr: str = "",
        profile: str = "minimal",
        delivery: str = "push",
        on_complete: str = "",
        max_retries: int = 0,
        **kwargs,
    ) -> str:
        if self.engine is None:
            return "调度器未初始化。"

        # Deduplication: reject if a task with the same name is already pending/running
        existing = [
            t for t in self.engine.list_timeline()
            if t.name == name and t.status.value in ("pending", "running")
        ]
        if existing:
            return f"任务「{name}」已存在（id: {existing[0].id[:8]}），未重复添加。"

        common = dict(
            profile=profile,
            reply_target=self.reply_target,
            delivery=delivery,
            max_retries=max_retries,
            on_complete=on_complete or None,
        )

        if trigger_type == "once":
            if not at:
                return "trigger_type=once 时必须提供 at 参数（ISO8601 格式）。"
            try:
                at_dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                if at_dt.tzinfo is None:
                    at_dt = at_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return f"at 参数格式无效，请使用 ISO8601（如 2026-04-29T17:00:00）：{at}"
            task = self.engine.schedule_once(name, instruction, at_dt, **common)
            return (
                f"已预约一次性任务。\n"
                f"task_id: {task.id}\n"
                f"名称: {task.name}\n"
                f"触发时间: {task.next_run_at}\n"
                f"投递方式: {delivery}"
            )

        if trigger_type == "interval":
            if interval_seconds <= 0:
                return "trigger_type=interval 时 interval_seconds 必须 > 0。"
            task = self.engine.schedule_interval(name, instruction, interval_seconds, **common)
            return (
                f"已预约周期性任务。\n"
                f"task_id: {task.id}\n"
                f"名称: {task.name}\n"
                f"首次触发: {task.next_run_at}\n"
                f"间隔: 每 {interval_seconds} 秒\n"
                f"投递方式: {delivery}"
            )

        if trigger_type == "cron":
            if not cron_expr:
                return "trigger_type=cron 时必须提供 cron_expr 参数（如 '0 8 * * *'）。"
            task = self.engine.schedule_cron(name, instruction, cron_expr, **common)
            return (
                f"已预约 Cron 任务。\n"
                f"task_id: {task.id}\n"
                f"名称: {task.name}\n"
                f"表达式: {cron_expr}\n"
                f"首次触发: {task.next_run_at}\n"
                f"投递方式: {delivery}"
            )

        return f"未知 trigger_type：{trigger_type!r}，请使用 once、interval 或 cron。"
