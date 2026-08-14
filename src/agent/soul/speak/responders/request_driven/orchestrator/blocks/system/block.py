from __future__ import annotations

from .build import build_system_layer
from ..core.base import BlockContext, ComposeTarget
from ..core.types import BlockId, BlockSnapshot


class SystemBlock:
    block_id: BlockId = "system"
    writes_to = frozenset({"system.role", "system.output_format"})

    def snapshot(self, ctx: BlockContext) -> BlockSnapshot:
        return BlockSnapshot(block="system", summary=ctx.mode)

    def refresh(self, ctx: BlockContext, decision, target: ComposeTarget, *, plan) -> None:
        if not decision.refresh:
            return
        target.frame.system = build_system_layer(
            mode=ctx.mode,
            output_format=ctx.reply_style.render_prompt(),
        )
        if target.bundle is not None:
            target.bundle.system = target.frame.system

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        if not decision.include:
            return
        frame = plan.prepared_frame
        if frame is not None:
            bundle.system = frame.system

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        return []

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return []
