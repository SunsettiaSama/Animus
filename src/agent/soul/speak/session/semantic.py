from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..chunk import SpeakTurnChunk


class SemanticSessionBoundary(Protocol):
    """语义型会话边界（候选信号待后续定稿）。"""

    def should_rotate(self, session_id: str, *, last_turn: SpeakTurnChunk) -> bool: ...

    def reason(self) -> str: ...


@dataclass
class TopicShiftSemanticBoundary:
    """基于关键词偏移的轻量语义边界（占位实现）。"""

    _last_reason: str = field(default="", init=False)
    _explicit_markers: tuple[str, ...] = ("/new", "/reset", "新话题", "换个话题")

    def should_rotate(self, session_id: str, *, last_turn: SpeakTurnChunk) -> bool:
        user_text = last_turn.user_text.strip().lower()
        for marker in self._explicit_markers:
            if marker.lower() in user_text:
                self._last_reason = f"explicit marker: {marker}"
                return True
        self._last_reason = ""
        return False

    def reason(self) -> str:
        return self._last_reason
