from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _default_agent_config() -> Any:
    from agent.profile import SubAgentConfig
    return SubAgentConfig()


@dataclass
class LogConfig:
    enabled: bool = True
    min_level: str = "debug"
    max_file_size_mb: float = 50.0
    include_react_steps: bool = False


@dataclass
class PlannerConfig:
    mode: str = "auto"
    tools: list[str] | None = field(default_factory=lambda: ["scratchpad"])
    allow_search: bool = False
    max_steps: int = 8
    max_retries: int = 3
    system_prompt_extra: str = ""
    memory_short_term: bool = True
    memory_long_term: bool = False
    finalize_keywords: list[str] = field(
        default_factory=lambda: ["开始执行", "可以", "就这样", "/start", "/finalize"]
    )


@dataclass
class ReplannerConfig:
    triggers: list[str] = field(
        default_factory=lambda: ["on_task_failed", "on_module_complete"]
    )
    max_cycles: int = 3
    timeout_budget: float | None = None
    confidence_threshold: float = 0.0
    result_summary_max_chars: int = 300
    failed_last_steps: int = 3


@dataclass
class OrchestratorConfig:
    plan_dir: str = "data/plans"
    parallel_limit: int = 4
    checkpoint: str = "per_module"
    human_edit: bool = True
    shadow_poll_interval: float = 1.5
    snapshot_triggers: list[str] = field(
        default_factory=lambda: ["initial", "pre_replan", "pre_human_patch"]
    )
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    replanner: ReplannerConfig = field(default_factory=ReplannerConfig)
    log: LogConfig = field(default_factory=LogConfig)


@dataclass
class PlanConfig:
    llm_cfg_path: str = "config/llm_core/config.yaml"
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    agent: Any = field(default_factory=_default_agent_config)
