from __future__ import annotations

from typing import Any

from runtime.scheduler.config import SchedulerConfig


def _sub_memory(long_term: bool = False) -> Any:
    from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.agent.memory.medium_term_config import MediumTermMemoryConfig
    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=long_term),
    )


def _sub_memory_none() -> Any:
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


def make_default_scheduler_config(
    llm_cfg_path: str = "config/llm_core/config.yaml",
    scheduler_dir: str = ".react/scheduler",
    **overrides,
) -> SchedulerConfig:
    profiles = _default_profiles()
    return SchedulerConfig(
        llm_cfg_path=llm_cfg_path,
        scheduler_dir=scheduler_dir,
        profiles=profiles,
        **overrides,
    )
