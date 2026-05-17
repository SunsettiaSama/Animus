from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    pending   = "pending"
    paused    = "paused"
    running   = "running"
    done      = "done"
    failed    = "failed"
    cancelled = "cancelled"


class DeliveryMode(str, Enum):
    push       = "push"
    silent     = "silent"
    store_only = "store_only"


@dataclass
class Trigger:
    type: str
    at: str | None = None
    interval_seconds: int | None = None
    cron_expr: str | None = None

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

    reply_target: dict | None    = None
    delivery: DeliveryMode       = DeliveryMode.push

    max_retries: int             = 0
    retry_count: int             = 0
    retry_delay_seconds: int     = 60

    on_complete: str | None      = None
    context: dict | None         = None

    command: dict | None         = None

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "name":             self.name,
            "instruction":      self.instruction,
            "trigger":          self.trigger.to_dict(),
            "config_profile":   self.config_profile,
            "status":           self.status.value,
            "created_at":       self.created_at,
            "next_run_at":      self.next_run_at,
            "last_run_at":      self.last_run_at,
            "last_result_path": self.last_result_path,
            "reply_target":     self.reply_target,
            "delivery":         self.delivery.value,
            "max_retries":      self.max_retries,
            "retry_count":      self.retry_count,
            "retry_delay_seconds": self.retry_delay_seconds,
            "on_complete":      self.on_complete,
            "context":          self.context,
            "command":          self.command,
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
