from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..journal.dice import DiceResult


class SurpriseGenerator(Protocol):
    """意外事件情节生成器协议。

    接收命运骰结果和当前上下文，生成一段描述"意外发生了什么"的叙事文本。
    与 ``LandmarkFiller`` 不同，它不依赖 Agent 的预设意图——
    它从虚空中召唤一件事情的发生。

    参数
    ----
    - ``dice``              — 命运骰结果（体验基调）
    - ``recent_memories``   — 近期记忆检索结果（提供叙事土壤）
    - ``profile_narrative`` — agent 画像自述（确保风格一致）
    """

    def generate(
        self,
        dice: DiceResult,
        recent_memories: list[str],
        profile_narrative: str,
    ) -> str:
        """返回意外事件的情节文本。"""
        ...


class NullSurpriseGenerator:
    """占位实现——无 LLM 时的降级，用骰点基调生成简单占位文本。"""

    def generate(
        self,
        dice: DiceResult,
        recent_memories: list[str],
        profile_narrative: str,
    ) -> str:
        return f"发生了一件意外的事：{dice.tendency}"
