from __future__ import annotations

from .runtime.control.consume import consume_guidance_emits
from ..core.base import BlockContext


def post_turn_guidance(ctx: BlockContext, plan) -> list[str]:
    control = plan.control_snapshot
    if control is None:
        control = ctx.io.inbound.guidance.control.active(ctx.session_id)
    if control is None:
        return ["compose_director: consume_emits skipped (no control)"]
    return consume_guidance_emits(
        ctx.session_id,
        control,
        pop_presence_share_at=ctx.pop_presence_share_at,
        pop_session_share_at=ctx.pop_session_share_at,
        use_session_share_queue=ctx.use_session_share_queue,
        mark_recall_unit_consumed=ctx.mark_recall_unit_consumed,
    )
