from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


def _sub_memory(long_term: bool = False) -> Any:
    from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.agent.memory.medium_term_config import MediumTermMemoryConfig
    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=long_term),
    )


def _default_profiles() -> dict[str, SubAgentProfile]:
    return {
        "minimal": SubAgentProfile(
            max_steps=10,
            memory=_sub_memory(),
            tool_package="executor",
            system_note="",
        ),
        "executor": SubAgentProfile(
            max_steps=15,
            memory=_sub_memory(),
            tool_package="executor",
            system_note=(
                "你是任务执行智能体。接收具体任务后直接执行并给出结果，"
                "不要委派给其他智能体。"
            ),
        ),
        "researcher": SubAgentProfile(
            max_steps=15,
            memory=_sub_memory(long_term=False),
            tool_package="researcher",
            system_note=(
                "你是一个专注于信息研究与知识整理的助手，"
                "善于通过网络搜索和知识库检索获取准确信息。"
            ),
        ),
        "researcher_with_memory": SubAgentProfile(
            max_steps=15,
            memory=_sub_memory(long_term=True),
            tool_package="researcher",
            tools=[
                "soul_memory_search",
                "soul_life_chronicle",
            ],
            system_note=(
                "你是一个专注于信息研究与知识整理的助手，"
                "善于通过网络搜索、知识库检索和 Soul 记忆/生活经历获取准确信息。"
                "重要发现应通过 knowledge_save 保存到知识库。"
            ),
        ),
        "analyst": SubAgentProfile(
            max_steps=12,
            memory=_sub_memory(),
            tool_package="analyst",
            system_note=(
                "你是一个专注于数据分析与计算推理的助手，"
                "善于精确计算、单位换算和定量分析。"
            ),
        ),
        "coder": SubAgentProfile(
            max_steps=15,
            memory=_sub_memory(),
            tool_package="code",
            system_note=(
                "你是一个专注于代码编写与执行的助手，"
                "善于编写 Python 脚本解决问题并操作文件系统。"
            ),
        ),
    }


@dataclass
class SubAgentProfile:
    max_steps: int = 10
    memory: Any = field(default_factory=_sub_memory)
    tool_package: str | None = None
    tools: list[str] | None = None
    system_note: str = ""


@dataclass
class SubAgentConfig:
    llm_cfg_path: str = "config/llm_core/config.yaml"
    profiles: dict[str, SubAgentProfile] = field(default_factory=_default_profiles)
    max_concurrent: int = 4
