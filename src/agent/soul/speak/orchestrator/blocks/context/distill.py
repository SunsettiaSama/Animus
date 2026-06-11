from __future__ import annotations

from ..core.base import BlockContext


def refresh_context_distill(ctx: BlockContext, decision, *, plan) -> None:
    if not decision.refresh:
        return
    if ctx.orchestrator._context is not None:
        ctx.orchestrator._context.distill_if_requested(ctx.session_id)
        plan.notes.append("director: context distill requested")
