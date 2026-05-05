from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


def _sub_memory(long_term: bool = False) -> "Any":
    """Return a MemoryConfig safe for sub-agents.

    Differences from the default MemoryConfig():
    - medium_term is DISABLED — sub-agents are one-shot tasks; enabling
      medium-term would write cross-session history to .react/memory/,
      the same directory used by the parent agent (storage pollution).
    - long_term is opt-in via the ``long_term`` flag.
    - L1 short-term remains enabled (needed for within-task reasoning).
    """
    from config.react.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.react.memory.medium_term_config import MediumTermMemoryConfig
    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=long_term),
    )


def _default_profiles() -> dict[str, Any]:
    return {
        # ── General purpose ──────────────────────────────────────────────────
        "minimal": CrewProfile(
            max_steps=10,
            memory=_sub_memory(),
            tools=None,
            system_note="",
        ),

        # ── Execution worker ─────────────────────────────────────────────────
        # Runs the actual sub-task; returns full step log so the caller
        # (usually a planner) can inspect what happened.
        "executor": CrewProfile(
            max_steps=15,
            memory=_sub_memory(),
            tools=None,
            system_note=(
                "你是任务执行智能体。接收具体任务后直接执行并给出结果，"
                "不要委派给其他智能体。"
            ),
            return_log=True,
        ),

        # ── Research ─────────────────────────────────────────────────────────
        # No persistent memory — searches and returns findings in-context.
        "researcher": CrewProfile(
            max_steps=15,
            memory=_sub_memory(long_term=False),
            tools=[
                "web_search", "web_fetch",
                "knowledge_hybrid_search", "knowledge_save", "knowledge_list",
            ],
            system_note=(
                "你是一个专注于信息研究与知识整理的助手，"
                "善于通过网络搜索和知识库检索获取准确信息。"
            ),
        ),

        # Researcher with L3 long-term read/write — can persist findings
        # to the shared knowledge base and recall across tasks.
        "researcher_with_memory": CrewProfile(
            max_steps=15,
            memory=_sub_memory(long_term=True),
            tools=[
                "web_search", "web_fetch",
                "knowledge_hybrid_search", "knowledge_save", "knowledge_list",
                "memory_recall",
            ],
            system_note=(
                "你是一个专注于信息研究与知识整理的助手，"
                "善于通过网络搜索、知识库检索和长期记忆获取准确信息。"
                "重要发现应通过 knowledge_save 保存到知识库。"
            ),
        ),

        # ── Analysis / calculation ───────────────────────────────────────────
        "analyst": CrewProfile(
            max_steps=12,
            memory=_sub_memory(),
            tools=["calculator", "unit_converter", "web_search", "get_datetime", "word_count"],
            system_note=(
                "你是一个专注于数据分析与计算推理的助手，"
                "善于精确计算、单位换算和定量分析。"
            ),
        ),

        # ── Orchestrator ─────────────────────────────────────────────────────
        # Decomposes the top-level task, fans out to executor/researcher/
        # analyst workers via delegate_task / spawn_all + await_all,
        # then synthesises a final answer.
        "planner": CrewProfile(
            max_steps=25,
            memory=_sub_memory(),
            tools=None,
            system_note=(
                "你是任务规划与编排智能体。接收任务后，拆解为子任务分别委派给 worker agent，"
                "观察全部结果后综合输出最终答案。不要自己直接执行任务，"
                "通过 delegate_task 或 spawn_all/await_all 派发。"
                "executor profile 适合通用执行任务，researcher 适合信息检索，"
                "analyst 适合计算分析。"
            ),
            recursive=True,
            return_log=True,
        ),
    }


@dataclass
class CrewProfile:
    max_steps: int = 10
    memory: Any = field(default_factory=_sub_memory)
    tools: list[str] | None = None
    system_note: str = ""
    recursive: bool = False
    return_log: bool = False


@dataclass
class CrewConfig:
    llm_cfg_path: str = "config/llm_core/config.yaml"
    profiles: dict[str, CrewProfile] = field(default_factory=_default_profiles)
    max_concurrent: int = 4


def flatten_recursive(cfg: CrewConfig) -> CrewConfig:
    flat = copy.deepcopy(cfg)
    for profile in flat.profiles.values():
        profile.recursive = False
    return flat
