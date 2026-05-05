from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    pending   = "pending"    # 等待触发
    running   = "running"    # 执行中
    done      = "done"       # 已完成（一次性任务终态）
    failed    = "failed"     # 执行失败
    cancelled = "cancelled"  # 手动取消


@dataclass
class Trigger:
    type: str                           # "once" | "interval"
    at: str | None = None               # ISO8601 datetime，仅 once 使用
    interval_seconds: int | None = None # 仅 interval 使用

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "at": self.at,
            "interval_seconds": self.interval_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Trigger:
        return cls(
            type=d["type"],
            at=d.get("at"),
            interval_seconds=d.get("interval_seconds"),
        )


@dataclass
class ScheduledTask:
    id: str
    name: str
    instruction: str
    trigger: Trigger
    config_profile: str     = "minimal"          # 对应 SchedulerConfig.profiles 的 key
    status: TaskStatus      = TaskStatus.pending
    created_at: str         = ""
    next_run_at: str | None = None   # 下次触发时间（ISO8601 UTC）
    last_run_at: str | None = None
    last_result_path: str | None = None

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
        )
