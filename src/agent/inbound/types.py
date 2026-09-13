from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RouteKind(str, Enum):
    speak = "speak"
    work = "work"


@dataclass(frozen=True)
class RouteContext:
    session_id: str
    channel_id: str
    gen_id: str


@dataclass(frozen=True)
class RouteDecision:
    route: RouteKind
    session_id: str
    question: str
    sample_id: str
    source: str
    confidence: float = 0.0
    score: float = 0.0
    features: list[float] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_ws_dict(self) -> dict[str, Any]:
        return {
            "type": "route_decision",
            "route": self.route.value,
            "session_id": self.session_id,
            "sample_id": self.sample_id,
            "source": self.source,
            "confidence": self.confidence,
            "score": self.score,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class PierceResult:
    ok: bool
    session_id: str
    true_route: RouteKind
    previous_route: RouteKind | None = None
    question: str = ""
    sample_id: str = ""
