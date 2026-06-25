from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GuidanceTrigger = Literal["init", "share_queue_full", "manual", "turn"]

NARRATIVE_MIN_CHARS = 100
NARRATIVE_MAX_CHARS = 280
BRIEF_MAX_CHARS = NARRATIVE_MAX_CHARS


@dataclass
class GuidanceControlState:
    """对话引导：100–200 字自然叙述（含回忆/分享时略可超出）。"""

    narrative: str
    version: int
    turn_span: int = 3
    remaining_turns: int = 3
    updated_turn_index: int = 0
    trigger: GuidanceTrigger = "init"
    share_linked: bool = False
    emit_share_queue_index: int | None = None
    emit_recall_unit_id: str | None = None

    @property
    def brief(self) -> str:
        return self.narrative

    @brief.setter
    def brief(self, value: str) -> None:
        self.narrative = value

    def snapshot(self) -> dict[str, Any]:
        return {
            "narrative": self.narrative,
            "brief": self.narrative,
            "version": self.version,
            "turn_span": self.turn_span,
            "remaining_turns": self.remaining_turns,
            "updated_turn_index": self.updated_turn_index,
            "trigger": self.trigger,
            "share_linked": self.share_linked,
            "emit_share_queue_index": self.emit_share_queue_index,
            "emit_recall_unit_id": self.emit_recall_unit_id,
        }

    @classmethod
    def from_plan(
        cls,
        *,
        narrative: str,
        version: int,
        turn_index: int,
        trigger: GuidanceTrigger,
        turn_span: int = 3,
        share_linked: bool = False,
        emit_share_queue_index: int | None = None,
        emit_recall_unit_id: str | None = None,
    ) -> GuidanceControlState:
        clipped = narrative.strip()[:NARRATIVE_MAX_CHARS]
        span = max(1, int(turn_span))
        return cls(
            narrative=clipped,
            version=version,
            turn_span=span,
            remaining_turns=span,
            updated_turn_index=turn_index,
            trigger=trigger,
            share_linked=share_linked,
            emit_share_queue_index=emit_share_queue_index,
            emit_recall_unit_id=emit_recall_unit_id,
        )


@dataclass
class GuidanceSessionRecord:
    current: GuidanceControlState | None = None
    history: list[str] = field(default_factory=list)
    next_version: int = 1

    def last_rhythm_brief(self) -> str:
        if self.current is not None and self.current.narrative.strip():
            return self.current.narrative.strip()
        if self.history:
            return self.history[-1].strip()
        return ""

    def has_control_history(self) -> bool:
        return self.current is not None or bool(self.history)
