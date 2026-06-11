from __future__ import annotations

from ...persona.interactor_portrait import interactor_pull_from_memory_result
from ..core.base import BlockContext
from ...director.types import DirectorPlan


def apply_recall(ctx: BlockContext, bundle, *, plan: DirectorPlan) -> None:
    if ctx.memory_compose is None or not plan.memory.include_recall:
        return
    if ctx.similar is None:
        return
    ctx.memory_compose.apply_similar_memories(bundle, ctx.similar)


def apply_portrait(ctx: BlockContext, bundle, *, plan: DirectorPlan) -> None:
    if ctx.memory_compose is None or not plan.memory.include_portrait:
        return
    if ctx.portrait is None:
        return
    pulled = interactor_pull_from_memory_result(ctx.portrait)
    ctx.orchestrator.interactor_portrait.apply_to_bundle(bundle, pulled)
