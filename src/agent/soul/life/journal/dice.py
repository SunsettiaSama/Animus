from __future__ import annotations

import random
from dataclasses import dataclass


# ── 命运骰表：10 个区间，覆盖 1~100 ─────────────────────────────────────────
# 每条：(上限, 体验氛围描述)
# 描述直接注入叙事引擎 prompt，LLM 据此决定情节的走向与基调

_DICE_TABLE: list[tuple[int, str]] = [
    ( 10, "事情完全没按预期走，中途出了岔子"),
    ( 20, "遇到了一些阻碍，比预想的要费力"),
    ( 30, "有点磕磕绊绊，不太顺利"),
    ( 40, "平平淡淡，没什么特别的"),
    ( 55, "大体如预期，比较顺利"),
    ( 65, "比预期稍微顺一些，有点小惊喜"),
    ( 75, "进展得相当顺利，感觉不错"),
    ( 85, "比想象中好很多，有值得记住的细节"),
    ( 95, "意外地顺利，收获了一些没预料到的东西"),
    (100, "出乎意料的好，留下了深刻印象"),
]


@dataclass(frozen=True)
class DiceResult:
    """一次命运骰的结果。

    ``tendency`` 是一句描述本次体验大概走向的普通话，
    直接注入叙事引擎 prompt，不携带额外的数值修正——
    情感偏向由 persona 层处理，骰子只负责给情节定基调。
    """
    value:    int
    tendency: str

    def __str__(self) -> str:
        return f"[d100={self.value}] {self.tendency}"


def roll_d100(seed: int | None = None) -> DiceResult:
    """投掷命运骰，返回 1~100 的点数及对应的体验基调描述。

    ``seed`` 仅用于测试时复现；正常使用不传。
    """
    rng = random.Random(seed) if seed is not None else random
    value = rng.randint(1, 100)
    for upper, tendency in _DICE_TABLE:
        if value <= upper:
            return DiceResult(value=value, tendency=tendency)
    return DiceResult(value=100, tendency=_DICE_TABLE[-1][1])
