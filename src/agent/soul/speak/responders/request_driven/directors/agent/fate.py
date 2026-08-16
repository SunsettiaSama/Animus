from __future__ import annotations

import random
from dataclasses import dataclass

# 软评分开口欲：0~10 极不想说 … 90~100 极想说
_FATE_BANDS: list[tuple[int, str]] = [
    (10, "非常不想说话"),
    (30, "不太想开口"),
    (50, "中性偏静，可接可不接"),
    (70, "愿意接话"),
    (89, "比较想说"),
    (100, "非常想说话"),
]

_DEFAULT_SCORE = 55
_STEP_PULL = 0.18  # 向中性均值回归，保证时间连续
_STEP_NOISE = 10.0  # 单步扰动幅度；避免帧间跳变


@dataclass(frozen=True)
class FateDiceRoll:
    """开口欲软评分（0~100）；带时间连续性，不直接改 speak_gate。"""

    roll: int
    tendency: str

    @property
    def speak_desire(self) -> int:
        return int(self.roll)


def fate_band_label(score: int) -> str:
    value = max(0, min(100, int(score)))
    for threshold, text in _FATE_BANDS:
        if value <= threshold:
            return text
    return _FATE_BANDS[-1][1]


def roll_fate_dice(
    *,
    previous: int | None = None,
    rng: random.Random | None = None,
) -> FateDiceRoll:
    """
    软机制命运骰：在上一拍分数邻域内漫步 + 轻度均值回归。

    - 冷启动落在中段，避免一上来极端
    - 相邻帧不会从 5 跳到 95
    """
    dice = rng or random
    if previous is None:
        score = int(dice.randint(_DEFAULT_SCORE - 15, _DEFAULT_SCORE + 15))
    else:
        prev = max(0, min(100, int(previous)))
        pull = (_DEFAULT_SCORE - prev) * _STEP_PULL
        noise = float(dice.uniform(-_STEP_NOISE, _STEP_NOISE))
        score = int(round(prev + pull + noise))
    score = max(0, min(100, score))
    return FateDiceRoll(roll=score, tendency=fate_band_label(score))
