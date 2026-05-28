from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent.soul.memory.domain import ActivationCue, ActivationSnapshot
from agent.soul.memory.emergence.speak import SpeakEmergence
from agent.soul.memory.emergence.spread import SpreadActivationService, spread_activation
from agent.soul.memory.emergence.types import HotEmergenceResult, PointEmergenceResult


@dataclass
class Emergence:
    """????????????????????"""

    spread: SpreadActivationService
    speak: SpeakEmergence

    def bind_enqueue(self, enqueue: Callable[[Callable[[], None]], None]) -> None:
        self.spread.bind_enqueue(enqueue)

    def activate_async(self, cue: ActivationCue) -> None:
        self.spread.expand_hot_async(cue)

    def expand_hot_async(self, cue: ActivationCue) -> None:
        self.spread.expand_hot_async(cue)

    def query_point_async(self, cue: ActivationCue) -> None:
        self.spread.query_point_async(cue)

    def get_snapshot(self, session_id: str) -> ActivationSnapshot | None:
        return self.spread.get_snapshot(session_id)

    def get_point_result(self, session_id: str, turn_index: int) -> PointEmergenceResult | None:
        return self.spread.get_point_result(session_id, turn_index)


__all__ = [
    "Emergence",
    "HotEmergenceResult",
    "PointEmergenceResult",
    "SpeakEmergence",
    "SpreadActivationService",
    "spread_activation",
]
