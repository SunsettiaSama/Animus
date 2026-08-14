from __future__ import annotations

from ..guidance.session_bridge import apply_session_social
from ..core.base import BlockContext, ComposeTarget
from ..core.types import BlockId, BlockSnapshot


class SocialBlock:
    block_id: BlockId = "social"
    writes_to = frozenset({"guidance.social_blocks", "meta.social_*"})

    def snapshot(self, ctx: BlockContext) -> BlockSnapshot:
        return BlockSnapshot(block="social", summary="")

    def refresh(self, ctx: BlockContext, decision, target: ComposeTarget, *, plan) -> None:
        return

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        if ctx.social is None or not decision.include:
            return
        apply_session_social(
            bundle,
            ctx.social,
            session_id=ctx.session_id,
            turn_index=ctx.turn_index,
            user_text=ctx.user_text,
            mode=ctx.mode,
            social_include=decision.include,
            social_armed=plan.social_armed,
        )

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        return []

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return []
