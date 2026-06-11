from __future__ import annotations

from ..core.base import BlockContext


def apply_context(ctx: BlockContext, decision, bundle) -> None:
    if not decision.include:
        bundle.guidance.context_distill = ""
        bundle.guidance.working_memory = ""
        return
    distiller = ctx.orchestrator._context
    if distiller is None or not ctx.session_id.strip():
        return
    distill_block, wm_block = distiller.session_context_blocks(
        ctx.session_id,
        generation=ctx.generation,
    )
    bundle.guidance.context_distill = distill_block
    bundle.guidance.working_memory = wm_block
    raw = distiller.prompt_block(ctx.session_id)
    if raw:
        bundle.persona.dialogue_compressed = raw
