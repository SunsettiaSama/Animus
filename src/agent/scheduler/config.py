from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _sub_memory(long_term: bool = False) -> Any:
    from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.agent.memory.medium_term_config import MediumTermMemoryConfig
    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=long_term),
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

    profiles: dict[str, Any] = field(default_factory=_default_profiles)

    @classmethod
    def from_dict(cls, d: dict) -> SchedulerConfig:
        return cls(
            scheduler_dir=d.get("scheduler_dir", ".react/scheduler"),
            poll_interval=float(d.get("poll_interval", 1.0)),
            llm_cfg_path=d.get("llm_cfg_path", "config/llm_core/config.yaml"),
            proactive_enabled=bool(d.get("proactive_enabled", True)),
        )
