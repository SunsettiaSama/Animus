from __future__ import annotations

from typing import Protocol

from .dice import DiceResult
from .item import Landmark


class LandmarkFiller(Protocol):
    """地标情节填充器协议。"""

    def fill(
        self,
        landmark: Landmark,
        profile_narrative: str,
        continuity_memories: list[str],
        dice: DiceResult,
    ) -> str:
        ...


class NullLandmarkFiller:
    """占位实现——无 LLM 时的降级，将意图与骰点倾向拼接返回。"""

    def fill(
        self,
        landmark: Landmark,
        profile_narrative: str,
        continuity_memories: list[str],
        dice: DiceResult,
    ) -> str:
        return f"{landmark.intention}（{dice.tendency}）"
