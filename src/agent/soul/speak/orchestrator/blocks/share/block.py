from __future__ import annotations

from ..core.base import BlockContext, ComposeTarget
from ..core.types import BlockId, BlockSnapshot
from .frame import attach_share_to_frame


class ShareBlock:
    block_id: BlockId = "share"
    writes_to = frozenset({
        "guidance.share_preview",
        "wants_share",
        "share_summary",
    })

    def snapshot(self, ctx: BlockContext) -> BlockSnapshot:
        share_state = ctx.orchestrator.share_compose_state(ctx.session_id)
        return BlockSnapshot(
            block="share",
            summary=share_state.summary[:200],
            extra={
                "wants_share": share_state.wants_share,
                "count": share_state.count,
            },
        )

    def refresh(self, ctx: BlockContext, decision, target: ComposeTarget, *, plan) -> None:
        if ctx.share_state is None:
            return
        attach_share_to_frame(
            target.frame,
            share_state=ctx.share_state,
            plan=plan.share,
        )
        if target.bundle is not None and plan.share.include_preview:
            target.bundle.guidance.share_preview = target.frame.guidance.share_preview
            target.bundle.wants_share = target.frame.wants_share
            target.bundle.share_summary = target.frame.share_summary

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        frame = plan.prepared_frame
        if frame is None:
            return
        if decision.include:
            bundle.guidance.share_preview = frame.guidance.share_preview
            bundle.wants_share = frame.wants_share
            bundle.share_summary = frame.share_summary
        else:
            bundle.guidance.share_preview = ""

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        return []

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return []
