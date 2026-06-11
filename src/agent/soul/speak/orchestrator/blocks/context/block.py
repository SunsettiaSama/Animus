from __future__ import annotations

from ..core.base import BlockContext, ComposeTarget
from ..core.types import BlockId
from .apply import apply_context
from .distill import refresh_context_distill
from .snapshot import context_snapshot


class ContextBlock:
    block_id: BlockId = "context"
    writes_to = frozenset({
        "guidance.context_distill",
        "guidance.working_memory",
        "persona.dialogue_compressed",
    })

    def snapshot(self, ctx: BlockContext):
        return context_snapshot(ctx)

    def refresh(self, ctx: BlockContext, decision, target: ComposeTarget, *, plan) -> None:
        refresh_context_distill(ctx, decision, plan=plan)

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        apply_context(ctx, decision, bundle)

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        return []

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return []
