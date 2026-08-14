from __future__ import annotations

import random
from dataclasses import dataclass

_FATE_TABLE: list[tuple[int, str]] = [
    (8, "有点小情绪，想轻轻打断当下节奏"),
    (18, "略想插一句，不完全顺着用户"),
    (35, "轻微走神，节奏可稍慢半拍"),
    (50, "中性：大体跟随用户节奏"),
    (65, "愿意顺着用户，少扰动"),
    (80, "耐心等待，先听再说"),
    (92, "想贴近用户节奏，稳住场面"),
    (100, "此刻很配合，尽量不抢话"),
]


@dataclass(frozen=True)
class FateDiceRoll:
    roll: int
    tendency: str


def roll_fate_dice(*, rng: random.Random | None = None) -> FateDiceRoll:
    """每帧一次；结果只作导演上下文，不直接改 speak_gate。"""
    dice = rng or random
    value = int(dice.randint(1, 100))
    tendency = _FATE_TABLE[-1][1]
    for threshold, text in _FATE_TABLE:
        if value <= threshold:
            tendency = text
            break
    return FateDiceRoll(roll=value, tendency=tendency)
