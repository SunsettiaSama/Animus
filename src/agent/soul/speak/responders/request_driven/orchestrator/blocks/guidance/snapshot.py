from __future__ import annotations

from ..core.base import BlockContext
from ..core.types import BlockSnapshot


def guidance_snapshot(ctx: BlockContext) -> BlockSnapshot:
    control = ctx.io.inbound.guidance.control.active(ctx.session_id)
    version = ctx.io.outbound.guidance.version(ctx.session_id)
    summary = control.narrative.strip() if control is not None else ""
    extra: dict = {}
    if control is not None:
        extra = {
            "remaining_turns": control.remaining_turns,
            "share_linked": control.share_linked,
            "trigger": control.trigger,
        }
    return BlockSnapshot(
        block="guidance",
        summary=summary[:200],
        version=version,
        extra=extra,
    )
