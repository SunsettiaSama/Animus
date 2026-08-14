from __future__ import annotations

from ..core.base import BlockContext, ComposeTarget, PlanSidecar
from .refresh import refresh_guidance


def apply_guidance(ctx: BlockContext, decision, bundle, *, plan) -> None:
    if not decision.include:
        bundle.guidance.control_arc = ""
        return
    frame = plan.prepared_frame
    if frame is None:
        return
    target = ComposeTarget(
        frame=frame,
        bundle=bundle,
        sidecar=PlanSidecar(),
    )
    refresh_guidance(ctx, decision, target, plan=plan)
    control = plan.control_snapshot
    if control is not None:
        bundle.meta["guidance_control_version"] = control.version
        bundle.meta["guidance_control_narrative"] = control.narrative
        bundle.meta["guidance_control_remaining"] = control.remaining_turns
        bundle.meta["guidance_emit_share_queue_index"] = control.emit_share_queue_index
        bundle.meta["guidance_emit_recall_unit_id"] = control.emit_recall_unit_id
