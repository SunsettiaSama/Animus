from __future__ import annotations

from ..core.base import BlockContext, ComposeTarget
from ..core.types import BlockId
from .apply import apply_guidance
from .post_turn import post_turn_guidance
from .refresh import refresh_guidance
from .snapshot import guidance_snapshot


class GuidanceBlock:
    block_id: BlockId = "guidance"
    writes_to = frozenset({"guidance.control_arc", "bundle.meta.guidance_control_*"})

    def snapshot(self, ctx: BlockContext):
        return guidance_snapshot(ctx)

    def refresh(self, ctx: BlockContext, decision, target: ComposeTarget, *, plan) -> None:
        refresh_guidance(ctx, decision, target, plan=plan)

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        apply_guidance(ctx, decision, bundle, plan=plan)

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        return []

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return post_turn_guidance(ctx, plan)
