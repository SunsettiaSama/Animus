from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..blocks.core.ledger import stale_map
from ..blocks.memory import (
    build_memory_inject_plan,
    has_topic_shift_signal,
    is_short_ack,
)
from ..blocks.registry import BlockRegistry
from ..blocks.share import build_share_compose_plan, share_queue_full
from .types import (
    BlockId,
    DirectorPlan,
    ModuleDecision,
    SocialArmedKind,
)

if TYPE_CHECKING:
    from ..orchestrator import SpeakOrchestrator


def _module_decision(
    block: BlockId,
    *,
    refresh: bool,
    include: bool,
    reason: str,
    guidance_trigger: str | None = None,
) -> ModuleDecision:
    return ModuleDecision(
        block=block,
        refresh=refresh,
        include=include,
        reason=reason,
        guidance_trigger=guidance_trigger,
    )


def decide_plan(
    orchestrator: SpeakOrchestrator,
    *,
    session_id: str,
    target_turn_index: int,
    user_text: str,
    generation: int = 0,
    bundle_meta: dict[str, Any] | None = None,
    cold_start: bool = False,
    social_armed: SocialArmedKind | None = None,
    silence_armed: bool = False,
    share_wants: bool = False,
    registry: BlockRegistry | None = None,
) -> DirectorPlan:
    sid = session_id.strip()
    reg = registry or orchestrator.block_registry
    ctx = orchestrator.pipeline_context(
        session_id=sid,
        turn_index=target_turn_index,
        user_text=user_text,
        generation=generation,
    )
    block_ctx = ctx.to_block_context()
    snapshots = reg.collect_snapshots(block_ctx)
    snapshot_map = {item.block: item for item in snapshots}

    stale: dict[BlockId, bool] = {}
    if orchestrator._session_port is not None and bundle_meta is not None:
        session = orchestrator._session_port.signals(sid)
        stale = stale_map(bundle_meta, orchestrator.io, session)

    guidance_snap = snapshot_map.get("guidance")
    remaining_turns = 0
    share_linked = False
    has_control = False
    if guidance_snap is not None:
        remaining_turns = int(guidance_snap.extra.get("remaining_turns", 0))
        share_linked = bool(guidance_snap.extra.get("share_linked", False))
        has_control = bool(guidance_snap.summary.strip())

    share_state = orchestrator.share_compose_state(sid)
    queue_count = share_state.count
    queue_full = share_queue_full(queue_count)
    use_session_queue = orchestrator.uses_session_share_queue(sid)
    share_plan = build_share_compose_plan(
        share_state=share_state,
        share_queue_full=queue_full,
        share_linked=share_linked,
        use_session_queue=use_session_queue,
    )

    arc_continues = remaining_turns > 0 and not has_topic_shift_signal(user_text)
    memory_plan = build_memory_inject_plan(
        user_text=user_text,
        cold_start=cold_start or not has_control,
        arc_continues=arc_continues,
    )

    short_ack = is_short_ack(user_text)
    notes: list[str] = []
    modules: list[ModuleDecision] = []

    for block in ("persona", "scene", "guidance"):
        block_stale = stale.get(block, False)
        if block == "persona":
            refresh = block_stale and not short_ack
            if cold_start:
                refresh = True
            modules.append(
                _module_decision(
                    "persona",
                    refresh=refresh,
                    include=True,
                    reason="cold_start" if cold_start else ("stale" if block_stale else "apply_only"),
                )
            )
        elif block == "scene":
            refresh = block_stale and bool(user_text.strip()) and not short_ack
            if cold_start:
                refresh = bool(user_text.strip())
            modules.append(
                _module_decision(
                    "scene",
                    refresh=refresh,
                    include=True,
                    reason="user_query" if refresh else "apply_only",
                )
            )
        elif block == "guidance":
            guidance_trigger = None
            refresh = False
            if cold_start or not has_control:
                refresh = True
                guidance_trigger = "init"
                notes.append("director: guidance init")
            elif share_plan.guidance_trigger == "share_queue_full":
                refresh = True
                guidance_trigger = "share_queue_full"
                notes.append("director: share_queue_full replan")
            elif arc_continues:
                refresh = False
                notes.append("director: guidance arc continues")
            elif block_stale or has_topic_shift_signal(user_text):
                refresh = True
                guidance_trigger = "turn"
                notes.append("director: guidance turn replan")
            modules.append(
                _module_decision(
                    "guidance",
                    refresh=refresh,
                    include=True,
                    reason=guidance_trigger or "apply_only",
                    guidance_trigger=guidance_trigger,
                )
            )

    context_snap = snapshot_map.get("context")
    buffer_count = 0
    if context_snap is not None:
        buffer_count = int(context_snap.extra.get("buffer_count", 0))
    context_refresh = buffer_count >= 4 and not short_ack
    modules.append(
        _module_decision(
            "context",
            refresh=context_refresh,
            include=not short_ack,
            reason="distill_chunk_full" if context_refresh else "read_cache",
        )
    )

    modules.append(
        _module_decision(
            "memory",
            refresh=False,
            include=memory_plan.include_recall or memory_plan.include_portrait,
            reason="pull_at_consume",
        )
    )

    social_include = social_armed is not None or silence_armed
    if social_armed is None and not silence_armed and not short_ack:
        social_include = True
    modules.append(
        _module_decision(
            "social",
            refresh=False,
            include=social_include,
            reason=social_armed or ("silence" if silence_armed else "default"),
        )
    )

    modules.append(
        _module_decision(
            "share",
            refresh=False,
            include=share_plan.include_preview,
            reason="wants_share" if share_plan.include_preview else "no_share",
        )
    )

    if share_wants and share_plan.include_preview:
        notes.append("director: share_wants signal")

    return DirectorPlan(
        session_id=sid,
        target_turn_index=target_turn_index,
        generation=generation,
        modules=tuple(modules),
        memory=memory_plan,
        share=share_plan,
        social_armed=social_armed,
        source_user_text=user_text.strip(),
        notes=notes,
    )
