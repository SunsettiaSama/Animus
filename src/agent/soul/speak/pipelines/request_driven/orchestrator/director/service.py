from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..pipeline.compose_pipeline import ComposePipeline
from ..pipeline.context import ComposePipelineContext
from ..blocks.system.role import SpeakTurnMode
from .decide import decide_plan
from .store import DirectorPlanStore
from .types import DirectorPlan

if TYPE_CHECKING:
    from ..bundle import SpeakPromptBundle
    from ..orchestrator import SpeakOrchestrator
    from agent.soul.speak.io.inbound.memory.compose_bridge import InboundMemoryComposeBridge


class ComposeDirector:
    """Compose 导演：决策 + plan 存储 + pipeline 委托。"""

    def __init__(
        self,
        orchestrator: SpeakOrchestrator,
        *,
        pipeline: ComposePipeline | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._store = DirectorPlanStore()
        self._pipeline = pipeline or orchestrator.compose_pipeline

    @property
    def store(self) -> DirectorPlanStore:
        return self._store

    @property
    def pipeline(self) -> ComposePipeline:
        return self._pipeline

    def invalidate_session(self, session_id: str) -> int:
        return self._store.bump_generation(session_id.strip())

    def load_plan(self, session_id: str, turn_index: int) -> DirectorPlan | None:
        return self._store.load(session_id, turn_index)

    def save_plan(self, plan: DirectorPlan) -> None:
        self._store.save(plan)

    def clear_session(self, session_id: str) -> None:
        self._store.clear_session(session_id)

    def is_plan_ready(self, session_id: str, turn_index: int) -> bool:
        plan = self.load_plan(session_id, turn_index)
        return plan is not None and plan.prepared_frame is not None

    def bootstrap_plan(
        self,
        session_id: str,
        *,
        target_turn_index: int,
        user_text: str,
        generation: int = 0,
        bundle_meta: dict[str, Any] | None = None,
        mode: SpeakTurnMode = "inbound",
    ) -> DirectorPlan:
        ctx = self._orchestrator.pipeline_context(
            session_id=session_id,
            turn_index=target_turn_index,
            user_text=user_text,
            generation=generation,
            mode=mode,
        )
        plan = self._pipeline.produce_plan(
            ctx,
            target_turn_index=target_turn_index,
            bundle_meta=bundle_meta,
            cold_start=True,
        )
        return plan

    def produce_plan(
        self,
        session_id: str,
        *,
        target_turn_index: int,
        user_text: str,
        generation: int = 0,
        bundle_meta: dict[str, Any] | None = None,
        mode: SpeakTurnMode = "inbound",
        agent_text: str = "",
        social_armed: str | None = None,
        silence_armed: bool = False,
        share_wants: bool = False,
    ) -> DirectorPlan:
        cold_start = self.load_plan(session_id, target_turn_index - 1) is None
        ctx = self._orchestrator.pipeline_context(
            session_id=session_id,
            turn_index=target_turn_index,
            user_text=user_text,
            generation=generation,
            mode=mode,
        )
        return self._pipeline.produce_plan(
            ctx,
            target_turn_index=target_turn_index,
            bundle_meta=bundle_meta,
            cold_start=cold_start and target_turn_index <= 1,
            social_armed=social_armed,
            silence_armed=silence_armed,
            share_wants=share_wants,
            agent_text=agent_text,
        )

    def apply_memory_kick(
        self,
        plan: DirectorPlan,
        memory_compose: InboundMemoryComposeBridge,
        *,
        user_text: str,
        ledger,
        mode: SpeakTurnMode = "inbound",
    ) -> list[str]:
        ctx = self._orchestrator.pipeline_context(
            session_id=plan.session_id,
            turn_index=plan.target_turn_index,
            user_text=user_text,
            generation=plan.generation,
            mode=mode,
            memory_compose=memory_compose,
        )
        return self._pipeline.kick_memory(plan, ctx, ledger)

    def finish_turn(
        self,
        plan: DirectorPlan,
        bundle: SpeakPromptBundle,
        ctx: ComposePipelineContext,
    ) -> SpeakPromptBundle:
        return self._pipeline.finish_turn(plan, bundle, ctx)

    def consume_emits(
        self,
        plan: DirectorPlan,
        *,
        pop_presence_share_at: Callable[[str, int], bool] | None = None,
        pop_session_share_at: Callable[[str, int], bool] | None = None,
        use_session_share_queue: bool = False,
        mark_recall_unit_consumed: Callable[[str, str], None] | None = None,
    ) -> list[str]:
        ctx = self._orchestrator.pipeline_context(
            session_id=plan.session_id,
            turn_index=plan.target_turn_index,
            user_text=plan.source_user_text,
            generation=plan.generation,
            pop_presence_share_at=pop_presence_share_at,
            pop_session_share_at=pop_session_share_at,
            mark_recall_unit_consumed=mark_recall_unit_consumed,
        )
        block_ctx = ctx.to_block_context()
        block_ctx.use_session_share_queue = use_session_share_queue
        return self._pipeline.registry.post_turn(plan, block_ctx)
