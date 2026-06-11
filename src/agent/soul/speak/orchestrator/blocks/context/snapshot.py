from __future__ import annotations

from ..core.base import BlockContext
from ..core.types import BlockSnapshot


def context_snapshot(ctx: BlockContext) -> BlockSnapshot:
    buffer_count = 0
    summary = ""
    if ctx.orchestrator._context is not None:
        snap = ctx.orchestrator._context.snapshot(ctx.session_id)
        buffer_count = int(snap.get("buffer_count", 0))
        distilled = snap.get("distilled")
        if isinstance(distilled, list) and distilled:
            summary = str(distilled[-1])[:200]
    return BlockSnapshot(
        block="context",
        summary=summary,
        extra={"buffer_count": buffer_count},
    )
