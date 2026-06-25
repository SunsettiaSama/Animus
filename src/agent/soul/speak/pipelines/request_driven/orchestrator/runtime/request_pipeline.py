from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.soul.speak.io.outbound.stream import SpeakStreamEvent

from ..state.core.delivery import DeliveryPlan


@dataclass
class RequestDrivenTurnResult:
    session_id: str
    answer: str = ""
    stream_events: list[SpeakStreamEvent] = field(default_factory=list)
    delivery_plan: DeliveryPlan | None = None
    notes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_speak_turn_result(self):
        from agent.soul.speak.service import SpeakTurnResult

        return SpeakTurnResult(
            session_id=self.session_id,
            answer=self.answer,
            bundle=None,  # type: ignore[arg-type]
            stream_events=list(self.stream_events),
            notes=list(self.notes),
            meta=dict(self.meta),
        )
