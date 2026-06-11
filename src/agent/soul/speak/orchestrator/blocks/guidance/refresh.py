from __future__ import annotations

from ...guidance.control.candidate_types import RecallPlannerCandidate
from ...guidance.inbound.persona_brief import (
    build_guidance_plan_request,
    stash_persona_outbound_brief,
)
from ...guidance.share.candidates import format_share_candidates, select_share_candidates
from ...persona.outbound.brief import collect_persona_outbound_brief
from ..core.base import BlockContext, ComposeTarget
from ..core.util import distilled_context


def _recall_candidates_from_bundle(bundle) -> tuple[RecallPlannerCandidate, ...]:
    raw = bundle.meta.get("guidance_recall_candidates")
    if not raw:
        return ()
    if isinstance(raw, tuple):
        return raw
    return tuple(raw)


def _share_preview_for_planner(ctx: BlockContext, bundle, *, include_in_planner: bool) -> tuple[str, tuple]:
    share_preview = bundle.guidance.share_preview.strip()
    share_candidates = ()
    if not include_in_planner or ctx.share_state is None or not ctx.share_state.events:
        return share_preview, share_candidates
    share_candidates = select_share_candidates(ctx.share_state.events)
    share_preview = format_share_candidates(
        share_candidates,
        summary=ctx.share_state.summary,
    )
    return share_preview, share_candidates


def refresh_guidance(
    ctx: BlockContext,
    decision,
    target: ComposeTarget,
    *,
    plan,
) -> None:
    bundle = target.bundle
    if bundle is None:
        return
    sid = ctx.session_id
    io = ctx.io
    if not decision.refresh:
        io.outbound.guidance.apply_to_bundle(bundle, sid)
        control = io.inbound.guidance.control.active(sid)
        if target.sidecar.control_snapshot is not None:
            control = target.sidecar.control_snapshot
        if target.assembly is not None:
            version = io.outbound.guidance.version(sid) or 0
            narrative = control.narrative.strip() if control is not None else ""
            target.assembly.set_slot("guidance", narrative=narrative, version=version)
        if control is not None:
            target.sidecar.control_snapshot = control
            plan.control_snapshot = control
        target.frame.guidance.control_arc = bundle.guidance.control_arc
        return

    text = distilled_context(bundle)
    share_preview, share_candidates = _share_preview_for_planner(
        ctx,
        bundle,
        include_in_planner=plan.share.include_in_planner,
    )
    persona_brief = collect_persona_outbound_brief(
        io,
        session_id=sid,
        layer=bundle.persona,
    )
    stash_persona_outbound_brief(bundle, persona_brief)
    guidance_trigger = decision.guidance_trigger or "turn"
    request = build_guidance_plan_request(
        session_id=sid,
        turn_index=ctx.turn_index,
        distilled_context=text,
        persona_brief=persona_brief,
        interactor_portrait=bundle.guidance.interactor_portrait.strip(),
        share_preview=share_preview,
        recall_preview=bundle.guidance.recall_preview.strip(),
        share_candidates=share_candidates,
        recall_candidates=_recall_candidates_from_bundle(bundle),
        share_queue_count=ctx.share_queue_count,
        share_queue_full=io.inbound.guidance.share_queue_full(ctx.share_queue_count),
        use_session_share_queue=ctx.use_session_share_queue,
        trigger=guidance_trigger,  # type: ignore[arg-type]
    )
    io.inbound.guidance.sync_for_compose(request, force=decision.refresh)
    io.outbound.guidance.apply_to_bundle(bundle, sid)
    control = io.inbound.guidance.control.active(sid)
    if target.assembly is not None:
        version = io.outbound.guidance.version(sid) or 0
        narrative = control.narrative.strip() if control is not None else ""
        target.assembly.set_slot("guidance", narrative=narrative, version=version)
    if control is not None:
        target.sidecar.control_snapshot = control
        plan.control_snapshot = control
    target.frame.guidance.control_arc = bundle.guidance.control_arc
