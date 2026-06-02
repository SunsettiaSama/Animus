from __future__ import annotations

import random
from dataclasses import dataclass


_DICE_TABLE: list[tuple[int, str]] = [
    (10, "事情完全没按预期走，中途出了岔子"),
    (20, "遇到了一些阻碍，比预想的要费力"),
    (30, "有点磕磕绊绊，不太顺利"),
    (40, "平平淡淡，没什么特别的"),
    (55, "大体如预期，比较顺利"),
    (65, "比预期稍微顺一些，有点小惊喜"),
    (75, "进展得相当顺利，感觉不错"),
    (85, "比想象中好很多，有值得记住的细节"),
    (95, "意外地顺利，收获了一些没预料到的东西"),
    (100, "出乎意料的好，留下了深刻印象"),
]


@dataclass(frozen=True)
class DiceResult:
    value: int
    tendency: str

    def __str__(self) -> str:
        return f"[d100={self.value}] {self.tendency}"


def roll_d100(seed: int | None = None) -> DiceResult:
    rng = random.Random(seed) if seed is not None else random
    value = rng.randint(1, 100)
    for upper, tendency in _DICE_TABLE:
        if value <= upper:
            return DiceResult(value=value, tendency=tendency)
    return DiceResult(value=100, tendency=_DICE_TABLE[-1][1])
