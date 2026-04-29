from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _default_profiles() -> dict[str, Any]:
    from config.react.tao_config import TaoConfig
    from config.react.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.react.memory.milestone_config import MilestoneConfig
    from config.react.persona_config import PersonaConfig

    return {
        "minimal": TaoConfig(max_steps=10),
        "with_memory": TaoConfig(
            max_steps=10,
            memory=MemoryConfig(
                long_term=LongTermMemoryConfig(enabled=True),
            ),
        ),
        "full": TaoConfig(
            max_steps=10,
            memory=MemoryConfig(
                long_term=LongTermMemoryConfig(enabled=True),
                milestone=MilestoneConfig(enabled=True),
            ),
            persona=PersonaConfig(enabled=True),
        ),
    }


@dataclass
class SchedulerConfig:
    scheduler_dir: str = ".react/scheduler"
    poll_interval: float = 1.0
    llm_cfg_path: str = "config/llm_core/config.yaml"

    # TaoConfig 预设（按名字索引），Runner 根据 task.config_profile 选择。
    # 使用 Any 避免在模块加载期导入 TaoConfig（防止循环引用）。
    profiles: dict[str, Any] = field(default_factory=_default_profiles)

    @classmethod
    def from_dict(cls, d: dict) -> SchedulerConfig:
        return cls(
            scheduler_dir=d.get("scheduler_dir", ".react/scheduler"),
            poll_interval=float(d.get("poll_interval", 1.0)),
            llm_cfg_path=d.get("llm_cfg_path", "config/llm_core/config.yaml"),
        )
