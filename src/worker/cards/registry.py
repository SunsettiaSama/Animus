"""Capability cards — unified SubAgent / Flow capability resolution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


def _sub_memory(long_term: bool = False) -> Any:
    from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
    from config.agent.memory.medium_term_config import MediumTermMemoryConfig

    return MemoryConfig(
        medium_term=MediumTermMemoryConfig(enabled=False),
        long_term=LongTermMemoryConfig(enabled=long_term),
    )


@dataclass
class CapabilityCard:
    id: str
    description: str = ""
    tool_package: str | None = None
    tools: tuple[str, ...] = ()
    max_steps: int = 10
    system_note: str = ""
    long_term_memory: bool = False

    def materialize(self):
        from worker.profile import SubAgentProfile

        tools = list(self.tools) if self.tools else None
        return SubAgentProfile(
            max_steps=self.max_steps,
            memory=_sub_memory(long_term=self.long_term_memory),
            tool_package=self.tool_package,
            tools=tools,
            system_note=self.system_note,
        )


def _profile_cards() -> dict[str, CapabilityCard]:
    return {
        "minimal": CapabilityCard(
            id="minimal",
            description="最小执行卡",
            tool_package="executor",
            max_steps=10,
        ),
        "executor": CapabilityCard(
            id="executor",
            description="通用任务执行",
            tool_package="executor",
            max_steps=15,
            system_note=(
                "你是任务执行智能体。接收具体任务后直接执行并给出结果，"
                "不要委派给其他智能体。"
            ),
        ),
        "researcher": CapabilityCard(
            id="researcher",
            description="信息研究与知识整理",
            tool_package="researcher",
            max_steps=15,
            system_note=(
                "你是一个专注于信息研究与知识整理的助手，"
                "善于通过网络搜索和知识库检索获取准确信息。"
            ),
        ),
        "researcher_with_memory": CapabilityCard(
            id="researcher_with_memory",
            description="带 Soul 记忆的研究卡",
            tool_package="researcher",
            tools=("soul_memory_search", "soul_life_chronicle"),
            max_steps=15,
            long_term_memory=True,
            system_note=(
                "你是一个专注于信息研究与知识整理的助手，"
                "善于通过网络搜索、知识库检索和 Soul 记忆/生活经历获取准确信息。"
                "重要发现应通过 knowledge_save 保存到知识库。"
            ),
        ),
        "analyst": CapabilityCard(
            id="analyst",
            description="数据分析与计算推理",
            tool_package="analyst",
            max_steps=12,
            system_note=(
                "你是一个专注于数据分析与计算推理的助手，"
                "善于精确计算、单位换算和定量分析。"
            ),
        ),
        "coder": CapabilityCard(
            id="coder",
            description="代码编写与执行",
            tool_package="code",
            max_steps=15,
            system_note=(
                "你是一个专注于代码编写与执行的助手，"
                "善于编写 Python 脚本解决问题并操作文件系统。"
            ),
        ),
    }


def _package_thin_cards() -> dict[str, CapabilityCard]:
    """One thin card per BUILTIN_PACKAGES name for DAG / coding flow."""
    from worker.tools.manager import BUILTIN_PACKAGES

    cards: dict[str, CapabilityCard] = {}
    for pkg in BUILTIN_PACKAGES:
        if pkg.name in cards:
            continue
        cards[pkg.name] = CapabilityCard(
            id=pkg.name,
            description=pkg.description or f"package:{pkg.name}",
            tool_package=pkg.name,
            max_steps=15,
            system_note="",
        )
    return cards


class CardRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, CapabilityCard] = {}
        self._cards.update(_profile_cards())
        # Thin package cards fill gaps; do not override richer profile cards.
        for cid, card in _package_thin_cards().items():
            if cid not in self._cards:
                self._cards[cid] = card

    def resolve(self, card_id: str) -> CapabilityCard:
        key = str(card_id or "").strip()
        if key not in self._cards:
            raise KeyError(f"unknown capability card: {card_id!r}")
        return self._cards[key]

    def materialize(self, card_id: str):
        return self.resolve(card_id).materialize()

    def ids(self) -> list[str]:
        return sorted(self._cards)


_DEFAULT_REGISTRY: CardRegistry | None = None


def get_card_registry() -> CardRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = CardRegistry()
    return _DEFAULT_REGISTRY


def resolve_capability(card_id: str) -> CapabilityCard:
    return get_card_registry().resolve(card_id)


def materialize_capability(card_id: str):
    return get_card_registry().materialize(card_id)
