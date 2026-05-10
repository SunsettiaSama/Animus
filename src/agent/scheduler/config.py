from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.scheduler.heartbeat.config import HeartbeatConfig


def _sub_memory(long_term: bool = False) -> Any:
    from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.agent.memory.medium_term_config import MediumTermMemoryConfig
    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=long_term),
    )


def _sub_memory_none() -> Any:
    """Memory config with both tiers disabled — used for light-context heartbeat precheck."""
    from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.agent.memory.medium_term_config import MediumTermMemoryConfig
    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=False),
    )


def _default_profiles() -> dict[str, Any]:
    from agent.profile import SubAgentProfile
    return {
        "minimal": SubAgentProfile(
            max_steps=10,
            memory=_sub_memory(),
        ),
        "with_memory": SubAgentProfile(
            max_steps=10,
            memory=_sub_memory(long_term=True),
        ),
        "full": SubAgentProfile(
            max_steps=10,
            memory=_sub_memory(long_term=True),
        ),
    }


@dataclass
class SchedulerConfig:
    scheduler_dir: str   = ".react/scheduler"
    poll_interval: float = 1.0
    llm_cfg_path: str    = "config/llm_core/config.yaml"

    # When False, all push-mode tasks are silenced at the global level.
    # Individual tasks can still be set to DeliveryMode.silent independently.
    proactive_enabled: bool = True

    # System note prepended to every sub-agent's system_note in scheduled runs.
    # Informs the agent about its context, available tools, and delivery channel.
    scheduler_system_note: str = ""

    # Default profile used when creating new tasks from the UI.
    default_profile: str = "minimal"

    # Maximum number of tasks that may run concurrently.
    max_concurrent: int = 3

    # Days to retain done/cancelled tasks before cleanup (0 = keep forever).
    task_retention_days: int = 30

    profiles: dict[str, Any] = field(default_factory=_default_profiles)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)

    # Communication tool rate limits
    comm_notify_rpm: int = 5
    comm_notify_rph: int = 20
    comm_bot_rpm:    int = 3
    comm_bot_rph:    int = 15

    @classmethod
    def from_dict(cls, d: dict) -> SchedulerConfig:
        inst = cls(
            scheduler_dir=d.get("scheduler_dir", ".react/scheduler"),
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
        # Restore per-profile max_steps from saved YAML
        for k, info in d.get("profiles", {}).items():
            if k in inst.profiles and isinstance(info, dict):
                inst.profiles[k].max_steps = int(info.get("max_steps", inst.profiles[k].max_steps))
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
