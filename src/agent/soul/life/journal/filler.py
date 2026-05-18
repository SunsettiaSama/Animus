from __future__ import annotations

from typing import Protocol

from .dice import DiceResult
from .item import Landmark


class LandmarkFiller(Protocol):
    """地标情节填充器协议。

    三路上下文 + 一枚命运骰 → 叙事文本。

    参数
    ----
    - ``landmark``          — 待填充的地标（含 intention / context）
    - ``profile_narrative`` — agent 画像自述
    - ``recent_memories``   — 记忆检索结果
    - ``recent_landmarks``  — 近 K 个已完成历史地标
    - ``dice``              — 命运骰结果，决定体验的质地倾向

    ``dice.tendency`` 应被注入 prompt，使叙事引擎向该倾向生成内容。
    """

    def fill(
        self,
        landmark: Landmark,
        profile_narrative: str,
        recent_memories: list[str],
        recent_landmarks: list[Landmark],
        dice: DiceResult,
    ) -> str:
        """返回填充后的情节文本。"""
        ...


class NullLandmarkFiller:
    """占位实现——无 LLM 时的降级，将意图与骰点倾向拼接返回。"""

    def fill(
        self,
        landmark: Landmark,
        profile_narrative: str,
        recent_memories: list[str],
        recent_landmarks: list[Landmark],
        dice: DiceResult,
    ) -> str:
        return f"{landmark.intention}（{dice.tendency}）"
