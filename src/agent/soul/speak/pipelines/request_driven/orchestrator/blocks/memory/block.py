from __future__ import annotations

from ..core.base import BlockContext, ComposeTarget, PromptBlock
from ..core.types import BlockId
from .apply import apply_portrait, apply_recall
from .kick import kick_memory_requests
from .snapshot import memory_snapshot


class MemoryBlock:
    block_id: BlockId = "memory"
    writes_to = frozenset({
        "guidance.recall_preview",
        "guidance.interactor_portrait",
    })

    def snapshot(self, ctx: BlockContext):
        return memory_snapshot(ctx)

    def refresh(self, ctx, decision, target: ComposeTarget, *, plan) -> None:
        return

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        if not decision.include:
            return
        apply_recall(ctx, bundle, plan=plan)
        apply_portrait(ctx, bundle, plan=plan)

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        if ctx.memory_compose is None:
            return []
        return kick_memory_requests(
            ctx.memory_compose,
            ctx.session_id,
            turn_index=plan.target_turn_index,
            user_text=ctx.user_text,
            plan=plan.memory,
            ledger=ledger,
        )

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return []
