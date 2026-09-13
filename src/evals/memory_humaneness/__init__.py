"""拟人化记忆 benchmark：换记忆基座对比回复行为（专家评判，非 RLHF）。

__init__ 保持轻量（PEP 562 惰性导出）：schema/judge 等子模块应可独立导入，
不被 graph 基座的重导入链（MemoryService → langchain/infra）绑架。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bases import GraphMemoryBase, NullMemoryBase, StackMemoryBase, preload
    from .judge import ExpertJudge, HeuristicJudge, JudgeVerdict
    from .runner import CaseRecord, HumanenessHarness
    from .schema import (
        AGENT_NAME,
        CATEGORIES,
        PERSONA_TEXT,
        HumanenessCase,
        MemorySeed,
        load_cases,
        validate_dataset,
    )

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # schema（轻）
    "AGENT_NAME": ("evals.memory_humaneness.schema", "AGENT_NAME"),
    "PERSONA_TEXT": ("evals.memory_humaneness.schema", "PERSONA_TEXT"),
    "CATEGORIES": ("evals.memory_humaneness.schema", "CATEGORIES"),
    "HumanenessCase": ("evals.memory_humaneness.schema", "HumanenessCase"),
    "MemorySeed": ("evals.memory_humaneness.schema", "MemorySeed"),
    "load_cases": ("evals.memory_humaneness.schema", "load_cases"),
    "validate_dataset": ("evals.memory_humaneness.schema", "validate_dataset"),
    # judge（轻）
    "ExpertJudge": ("evals.memory_humaneness.judge", "ExpertJudge"),
    "HeuristicJudge": ("evals.memory_humaneness.judge", "HeuristicJudge"),
    "JudgeVerdict": ("evals.memory_humaneness.judge", "JudgeVerdict"),
    # bases / runner（graph 基座导入链重）
    "GraphMemoryBase": ("evals.memory_humaneness.bases", "GraphMemoryBase"),
    "StackMemoryBase": ("evals.memory_humaneness.bases", "StackMemoryBase"),
    "NullMemoryBase": ("evals.memory_humaneness.bases", "NullMemoryBase"),
    "preload": ("evals.memory_humaneness.bases", "preload"),
    "CaseRecord": ("evals.memory_humaneness.runner", "CaseRecord"),
    "HumanenessHarness": ("evals.memory_humaneness.runner", "HumanenessHarness"),
}

__all__ = list(_LAZY_IMPORTS)


def __getattr__(name: str):
    entry = _LAZY_IMPORTS.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr = entry
    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value
    return value
