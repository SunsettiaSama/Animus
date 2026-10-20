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


_REFLECTION_SOUL_TOOLS = (
    "soul_persona",
    "soul_memory_search",
    "soul_life_chronicle",
    "soul_life_hot",
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
        "reflection": SubAgentProfile(
            max_steps=15,
            memory=_sub_memory(long_term=True),
            tools=list(_REFLECTION_SOUL_TOOLS),
            system_note=(
                "你是 Agent 的自我叙事层，可进行日终自我反省。"
                "可用 soul_persona / soul_memory_search / soul_life_chronicle / "
                "soul_life_hot 查阅人格、记忆与生活经历后再总结。"
            ),
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
