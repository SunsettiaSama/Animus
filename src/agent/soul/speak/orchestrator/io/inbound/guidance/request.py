from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.orchestrator.blocks.guidance.control_types import (
    GuidanceTrigger,
    RecallPlannerCandidate,
    SharePlannerCandidate,
)
from agent.soul.speak.orchestrator.blocks.persona import PersonaOutboundBrief


@dataclass(frozen=True)
class GuidancePlanRequest:
    session_id: str
    turn_index: int
    distilled_context: str = ""
    persona_portrait: str = ""
    persona_brief: PersonaOutboundBrief | None = None
    interactor_portrait: str = ""
    share_preview: str = ""
    recall_preview: str = ""
    share_candidates: tuple[SharePlannerCandidate, ...] = ()
    recall_candidates: tuple[RecallPlannerCandidate, ...] = ()
    share_queue_count: int = 0
    share_queue_full: bool = False
    trigger: GuidanceTrigger = "turn"
    use_session_share_queue: bool = False
