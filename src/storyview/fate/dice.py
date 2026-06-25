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

_STORY_DIRECTION_TABLE: list[tuple[int, str]] = [
    (25, "收束当前线索，让这一拍给出清楚的判断或确认。"),
    (50, "引入一个可处理的新信息，但不要扩大成另一条主线。"),
    (75, "制造一个轻微代价或新约束，让角色下一步必须调整做法。"),
    (100, "打开一个新的机会或疑点，让场景弧向下一拍推进。"),
]

_DECISION_IMPORTANCE_TABLE: list[tuple[int, str, float, str, int]] = [
    (25, "这是一个轻量选择，只在当下留下短暂触感。", 0.35, "短暂", 0),
    (55, "这是一个普通选择，会轻微改变接下来的注意力。", 0.5, "短促", 1),
    (80, "这是一个有分量的选择，会让这段经历在心里多停留一会儿。", 0.65, "中等", 2),
    (100, "这是一个关键转向，会成为这段经历之后被记住的核心。", 0.8, "较长", 3),
]


@dataclass(frozen=True)
class DiceResult:
    value: int
    tendency: str

    def __str__(self) -> str:
        return f"[d100={self.value}] {self.tendency}"


@dataclass(frozen=True)
class DecisionImportance:
    value: int
    hint: str
    salience: float
    mood_span: str
    linger_days: int


def roll_d100(seed: int | None = None) -> DiceResult:
    rng = random.Random(seed) if seed is not None else random
    value = rng.randint(1, 100)
    for upper, tendency in _DICE_TABLE:
        if value <= upper:
            return DiceResult(value=value, tendency=tendency)
    return DiceResult(value=100, tendency=_DICE_TABLE[-1][1])


def roll_story_direction(seed: int | None = None) -> DiceResult:
    rng = random.Random(seed) if seed is not None else random
    value = rng.randint(1, 100)
    for upper, hint in _STORY_DIRECTION_TABLE:
        if value <= upper:
            return DiceResult(value=value, tendency=hint)
    return DiceResult(value=100, tendency=_STORY_DIRECTION_TABLE[-1][1])


def roll_decision_importance(seed: int | None = None) -> DecisionImportance:
    rng = random.Random(seed) if seed is not None else random
    value = rng.randint(1, 100)
    for upper, hint, salience, mood_span, linger_days in _DECISION_IMPORTANCE_TABLE:
        if value <= upper:
            return DecisionImportance(
                value=value,
                hint=hint,
                salience=salience,
                mood_span=mood_span,
                linger_days=linger_days,
            )
    _, hint, salience, mood_span, linger_days = _DECISION_IMPORTANCE_TABLE[-1]
    return DecisionImportance(
        value=100,
        hint=hint,
        salience=salience,
        mood_span=mood_span,
        linger_days=linger_days,
    )
