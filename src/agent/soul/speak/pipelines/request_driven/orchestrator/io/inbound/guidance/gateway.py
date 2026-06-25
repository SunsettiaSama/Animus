from __future__ import annotations

from config.soul.presence.config import SHARE_INTENT_QUEUE_MAX_ITEMS

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance import (
    GuidanceControlService,
    GuidancePlanInput,
)

from .request import GuidancePlanRequest


class InboundGuidanceGateway:
    """Guidance 入站：接收 compose 上下文，触发引导规划。"""

    def __init__(self, control: GuidanceControlService) -> None:
        self._control = control

    @property
    def control(self) -> GuidanceControlService:
        return self._control

    def clear_control_arc(self, session_id: str) -> None:
        self._control.clear_control_arc(session_id)

    def _to_plan_input(self, request: GuidancePlanRequest) -> GuidancePlanInput:
        entry = self._control.session_record(request.session_id)
        brief = request.persona_brief
        portrait = request.persona_portrait.strip()
        if brief is not None:
            portrait = brief.portrait_for_planner or portrait
        return GuidancePlanInput(
            session_id=request.session_id,
            turn_index=request.turn_index,
            distilled_context=request.distilled_context,
            persona_portrait=portrait,
            persona_brief=brief,
            interactor_portrait=request.interactor_portrait,
            share_preview=request.share_preview,
            recall_preview=request.recall_preview,
            share_candidates=request.share_candidates,
            recall_candidates=request.recall_candidates,
            last_rhythm_brief=entry.last_rhythm_brief(),
            share_queue_count=request.share_queue_count,
            share_queue_full=request.share_queue_full,
            trigger=request.trigger,
        )

    def plan(self, request: GuidancePlanRequest):
        return self._control.plan_and_set(self._to_plan_input(request))

    def sync_for_compose(
        self,
        request: GuidancePlanRequest,
        *,
        force: bool = False,
    ) -> bool:
        """被动化：仅导演显式 force 时触发 replan。"""
        if not force:
            return False
        self.plan(request)
        return True

    @staticmethod
    def share_queue_full(count: int) -> bool:
        return count >= SHARE_INTENT_QUEUE_MAX_ITEMS
