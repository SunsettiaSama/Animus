from __future__ import annotations

from config.soul.presence.config import SHARE_INTENT_QUEUE_MAX_ITEMS

from ...director.types import ShareComposePlan
from ...guidance.share.state import ShareComposeState


def build_share_compose_plan(
    *,
    share_state: ShareComposeState,
    share_queue_full: bool,
    share_linked: bool,
    use_session_queue: bool,
) -> ShareComposePlan:
    wants = share_state.wants_share
    include_preview = wants and bool(share_state.events or share_state.summary.strip())
    include_in_planner = include_preview
    trigger = None
    if share_queue_full and not share_linked:
        trigger = "share_queue_full"
    return ShareComposePlan(
        include_preview=include_preview,
        include_in_planner=include_in_planner,
        guidance_trigger=trigger,
        share_queue_count=share_state.count,
        share_linked=share_linked,
        deferred_use_session_queue=use_session_queue,
    )


def share_queue_full(count: int) -> bool:
    return count >= SHARE_INTENT_QUEUE_MAX_ITEMS
