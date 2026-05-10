from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    pending   = "pending"    # 等待触发
    paused    = "paused"     # 已暂停（不会触发，可恢复）
    running   = "running"    # 执行中
    done      = "done"       # 已完成（一次性任务终态）
    failed    = "failed"     # 执行失败（重试次数耗尽）
    cancelled = "cancelled"  # 手动取消


class DeliveryMode(str, Enum):
    push       = "push"        # 完成后主动推送到 reply_target（默认）
    silent     = "silent"      # 只存结果文件，不推送（任务链中间步骤）
    store_only = "store_only"  # 写入长期记忆，不推送


@dataclass
class Trigger:
    type: str                           # "once" | "interval" | "cron"
    at: str | None = None               # ISO8601 datetime，仅 once 使用
    interval_seconds: int | None = None # 仅 interval 使用
    cron_expr: str | None = None        # cron 表达式，仅 cron 使用（e.g. "0 8 * * *"）

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "at": self.at,
            "interval_seconds": self.interval_seconds,
            "cron_expr": self.cron_expr,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Trigger:
        return cls(
            type=d["type"],
            at=d.get("at"),
            interval_seconds=d.get("interval_seconds"),
            cron_expr=d.get("cron_expr"),
        )


@dataclass
class ScheduledTask:
    id: str
    name: str
    instruction: str
    trigger: Trigger
    config_profile: str          = "minimal"
    status: TaskStatus           = TaskStatus.pending
    created_at: str              = ""
    next_run_at: str | None      = None
    last_run_at: str | None      = None
    last_result_path: str | None = None

    # ── Delivery ──────────────────────────────────────────────────────────────
    # reply_target: WHERE to send (channel routing — set from session context)
    # delivery:     WHETHER/HOW to notify (agent-controllable)
    reply_target: dict | None    = None
    delivery: DeliveryMode       = DeliveryMode.push

    # ── Retry ─────────────────────────────────────────────────────────────────
    max_retries: int             = 0    # 0 = no retry
    retry_count: int             = 0    # attempts so far
    retry_delay_seconds: int     = 60

    # ── Task chain ────────────────────────────────────────────────────────────
    # on_complete: instruction template for chained task; supports {result} placeholder
    on_complete: str | None      = None
    context: dict | None         = None  # static variables injected into on_complete template

    # ── EventCommand (optional structured command) ────────────────────────────
    # Stores the original EventCommand template so the frontend can re-edit it.
    # instruction is always the rendered execution string; command is UI metadata.
    command: dict | None         = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "instruction": self.instruction,
            "trigger": self.trigger.to_dict(),
            "config_profile": self.config_profile,
            "status": self.status.value,
            "created_at": self.created_at,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "last_result_path": self.last_result_path,
            "reply_target": self.reply_target,
            "delivery": self.delivery.value,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "retry_delay_seconds": self.retry_delay_seconds,
            "on_complete": self.on_complete,
            "context": self.context,
            "command": self.command,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ScheduledTask:
        return cls(
            id=d["id"],
            name=d["name"],
            instruction=d["instruction"],
            trigger=Trigger.from_dict(d["trigger"]),
            config_profile=d.get("config_profile", "minimal"),
            status=TaskStatus(d.get("status", "pending")),
            created_at=d.get("created_at", ""),
            next_run_at=d.get("next_run_at"),
            last_run_at=d.get("last_run_at"),
            last_result_path=d.get("last_result_path"),
            reply_target=d.get("reply_target"),
            delivery=DeliveryMode(d.get("delivery", "push")),
            max_retries=d.get("max_retries", 0),
            retry_count=d.get("retry_count", 0),
            retry_delay_seconds=d.get("retry_delay_seconds", 60),
            on_complete=d.get("on_complete"),
            context=d.get("context"),
            command=d.get("command"),
        )
