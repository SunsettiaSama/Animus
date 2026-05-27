from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol

from ...chunk import SpeakTurnChunk


class SemanticSessionBoundary(Protocol):
    """语义型会话边界。"""

    def should_rotate(self, session_id: str, *, last_turn: SpeakTurnChunk) -> bool: ...

    def reason(self) -> str: ...

    def on_session_rotate(self, session_id: str) -> None: ...


class EmbeddingBackend(Protocol):
    def embed(self, text: str) -> list[float]: ...


def cosine_distance(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 1.0
    similarity = dot / (norm_left * norm_right)
    return 1.0 - similarity


@dataclass
class TopicShiftSemanticBoundary:
    """显式话题切换标记（/new、换个话题 等）。"""

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

    def on_session_rotate(self, session_id: str) -> None:
        _ = session_id


@dataclass
class EmbeddingSemanticBoundary:
    """embedding 语义距离：与当前会话锚点差距过大则切分。"""

    embedder: EmbeddingBackend
    distance_threshold: float = 0.42
    _last_reason: str = field(default="", init=False)
    _anchors: dict[str, list[float]] = field(default_factory=dict)

    def should_rotate(self, session_id: str, *, last_turn: SpeakTurnChunk) -> bool:
        text = last_turn.user_text.strip()
        if not text:
            self._last_reason = ""
            return False

        vector = self.embedder.embed(text)
        anchor = self._anchors.get(session_id)
        if anchor is None:
            self._anchors[session_id] = vector
            self._last_reason = ""
            return False

        distance = cosine_distance(anchor, vector)
        if distance >= self.distance_threshold:
            self._last_reason = (
                f"embedding distance {distance:.3f} >= {self.distance_threshold:.3f}"
            )
            return True

        self._last_reason = ""
        return False

    def reason(self) -> str:
        return self._last_reason

    def on_session_rotate(self, session_id: str) -> None:
        self._anchors.pop(session_id, None)


@dataclass
class CompositeSemanticBoundary:
    """显式标记 + embedding 语义距离。"""

    explicit: TopicShiftSemanticBoundary = field(default_factory=TopicShiftSemanticBoundary)
    embedding: EmbeddingSemanticBoundary | None = None
    _last_reason: str = field(default="", init=False)

    def should_rotate(self, session_id: str, *, last_turn: SpeakTurnChunk) -> bool:
        if self.explicit.should_rotate(session_id, last_turn=last_turn):
            self._last_reason = self.explicit.reason()
            return True
        if self.embedding is not None and self.embedding.should_rotate(session_id, last_turn=last_turn):
            self._last_reason = self.embedding.reason()
            return True
        self._last_reason = ""
        return False

    def reason(self) -> str:
        return self._last_reason

    def on_session_rotate(self, session_id: str) -> None:
        self.explicit.on_session_rotate(session_id)
        if self.embedding is not None:
            self.embedding.on_session_rotate(session_id)
