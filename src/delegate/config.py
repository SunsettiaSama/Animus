from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _default_profiles() -> dict[str, Any]:
    from config.react.memory.memory_config import MemoryConfig

    return {
        "minimal": DelegateProfile(
            max_steps=10,
            memory=MemoryConfig(),
            tools=None,
            system_note="",
        ),
        "researcher": DelegateProfile(
            max_steps=15,
            memory=MemoryConfig(),
            tools=["web_search", "web_fetch", "knowledge_hybrid_search", "knowledge_save", "knowledge_list"],
            system_note="你是一个专注于信息研究与知识整理的助手，善于通过网络搜索和知识库检索获取准确信息。",
        ),
        "analyst": DelegateProfile(
            max_steps=12,
            memory=MemoryConfig(),
            tools=["calculator", "unit_converter", "web_search", "get_datetime", "word_count"],
            system_note="你是一个专注于数据分析与计算推理的助手，善于精确计算、单位换算和定量分析。",
        ),
    }


@dataclass
class DelegateProfile:
    max_steps: int = 10
    memory: Any = field(default_factory=lambda: _import_memory_config())
    tools: list[str] | None = None
    system_note: str = ""


@dataclass
class DelegateConfig:
    llm_cfg_path: str = "config/llm_core/config.yaml"
    profiles: dict[str, DelegateProfile] = field(default_factory=_default_profiles)
    max_concurrent: int = 4


def _import_memory_config():
    from config.react.memory.memory_config import MemoryConfig
    return MemoryConfig()


# ── Backward-compatible aliases ───────────────────────────────────────────────

SubAgentProfile = DelegateProfile
SubAgentConfig  = DelegateConfig
