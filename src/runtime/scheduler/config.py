from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config.storage import StorageConfig, resolve_cache_path
from runtime.scheduler.heartbeat_config import HeartbeatConfig


@dataclass
class SchedulerConfig:
    """调度器配置。

    profiles 字段存放 task.config_profile 名到 profile 对象的映射。
    profile 对象类型为 Any（agent 层注入 SubAgentProfile；纯 runtime 场景可传任意 dict）。
    默认值为空字典；由调用方（如 ``agent.heartbeat.make_default_scheduler_config``）注入默认 profiles。
    """

    scheduler_dir: str   = ".react/scheduler"
    poll_interval: float = 1.0
    llm_cfg_path: str    = "config/llm_core/config.yaml"

    proactive_enabled: bool = True

    scheduler_system_note: str = ""

    default_profile: str = "minimal"

    max_concurrent: int = 3

    task_retention_days: int = 30

    profiles: dict[str, Any] = field(default_factory=dict)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)

    comm_notify_rpm: int = 5
    comm_notify_rph: int = 20
    comm_bot_rpm:    int = 3
    comm_bot_rph:    int = 15

    @classmethod
    def from_dict(cls, d: dict) -> SchedulerConfig:
        default_scheduler_dir = StorageConfig().scheduler_dir
        inst = cls(
            scheduler_dir=resolve_cache_path(
                str(d.get("scheduler_dir") or ""),
                default=default_scheduler_dir,
            ),
            poll_interval=float(d.get("poll_interval", 1.0)),
            llm_cfg_path=d.get("llm_cfg_path", "config/llm_core/config.yaml"),
            proactive_enabled=bool(d.get("proactive_enabled", True)),
            scheduler_system_note=d.get("scheduler_system_note", ""),
            default_profile=d.get("default_profile", "minimal"),
            max_concurrent=int(d.get("max_concurrent", 3)),
            task_retention_days=int(d.get("task_retention_days", 30)),
            heartbeat=HeartbeatConfig.from_dict(d.get("heartbeat", {})),
            comm_notify_rpm=int(d.get("comm_notify_rpm", 5)),
            comm_notify_rph=int(d.get("comm_notify_rph", 20)),
            comm_bot_rpm=int(d.get("comm_bot_rpm", 3)),
            comm_bot_rph=int(d.get("comm_bot_rph", 15)),
        )
        return inst

    def to_dict(self) -> dict:
        profiles_out = {}
        for k, p in self.profiles.items():
            profiles_out[k] = {"max_steps": getattr(p, "max_steps", 10)}
        return {
            "scheduler_dir":        self.scheduler_dir,
            "poll_interval":        self.poll_interval,
            "llm_cfg_path":         self.llm_cfg_path,
            "proactive_enabled":    self.proactive_enabled,
            "scheduler_system_note": self.scheduler_system_note,
            "default_profile":      self.default_profile,
            "max_concurrent":       self.max_concurrent,
            "task_retention_days":  self.task_retention_days,
            "profiles":             profiles_out,
            "heartbeat":            self.heartbeat.to_dict(),
            "comm_notify_rpm":      self.comm_notify_rpm,
            "comm_notify_rph":      self.comm_notify_rph,
            "comm_bot_rpm":         self.comm_bot_rpm,
            "comm_bot_rph":         self.comm_bot_rph,
        }
