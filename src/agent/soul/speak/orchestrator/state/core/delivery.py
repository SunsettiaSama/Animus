from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import Continuity, normalize_continuity


@dataclass(frozen=True)
class ReplySegment:
    text: str
    wait_ms: int
    wait_reason: str = ""
    continuity: Continuity = "finish"

    def snapshot(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "wait_ms": self.wait_ms,
            "wait_reason": self.wait_reason,
            "continuity": self.continuity,
        }


@dataclass(frozen=True)
class DeliveryPlan:
    """对话导演产出：分段回复 + 每段等待时间。"""

    segments: tuple[ReplySegment, ...]
    continuity: Continuity = "finish"
    sample_narration: str = ""
    plan_id: str = ""
    turn_index: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "turn_index": self.turn_index,
            "continuity": self.continuity,
            "sample_narration": self.sample_narration,
            "segments": [seg.snapshot() for seg in self.segments],
        }

    @property
    def is_empty(self) -> bool:
        return not self.segments


def build_delivery_plan(
    *,
    segments: list[ReplySegment],
    continuity: str = "finish",
    sample_narration: str = "",
    plan_id: str = "",
    turn_index: int = 0,
) -> DeliveryPlan:
    normalized_segments = tuple(segments)
    return DeliveryPlan(
        segments=normalized_segments,
        continuity=normalize_continuity(continuity),
        sample_narration=sample_narration.strip(),
        plan_id=plan_id.strip(),
        turn_index=turn_index,
    )
