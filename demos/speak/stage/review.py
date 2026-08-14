from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RhythmReview:
    """
    伪学习快照：上一轮交互复盘。

    - abstract：1~2 句原则，注入每拍节奏上下文
    - summary：约 500 字复盘，供下次 cold/hot init 定对话弧
    """

    abstract: str = ""
    summary: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.abstract.strip() or self.summary.strip())

    def snapshot(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "summary": self.summary,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RhythmReview:
        return cls(
            abstract=str(payload.get("abstract") or "").strip(),
            summary=str(payload.get("summary") or "").strip(),
        )


# 连续同 gate 警示阈值（硬编码，便于试 scale）
GATE_STREAK_WARN = 3
GATE_STREAK_SEVERE = 5


def gate_streak_warning(gate: str, streak: int) -> str:
    """根据连续同指令次数生成警示文案；未达阈值则空串。"""
    token = gate.strip() or "?"
    if streak >= GATE_STREAK_SEVERE:
        return (
            f"【严重警告】你已连续 {streak} 次采用同一指令 gate={token}。"
            f"请停一下自问：是否真的决定继续 {token}？"
            "若对话弧 / 待分享 / 用户留白在催开口，应改 brew 或 speak；"
            f"若坚持 {token}，必须在 reason 里写清「为什么这一拍仍不能改」。"
        )
    if streak >= GATE_STREAK_WARN:
        return (
            f"【警告】你已连续 {streak} 次采用同一指令 gate={token}。"
            "请审视这一决定是否僵住了：材料变了没有？该听还是该轻声补一句？"
            f"不要只因为上一拍也是 {token} 就惯性复读。"
        )
    return ""


def review_abstract_block(review: RhythmReview | None) -> list[str]:
    if review is None or not review.abstract.strip():
        return []
    return [
        "",
        "## 复盘原则（伪学习 abstract）",
        review.abstract.strip(),
    ]


def streak_warning_block(gate: str, streak: int) -> list[str]:
    text = gate_streak_warning(gate, streak)
    if not text:
        return []
    return ["", "## 连续指令警示", text]
