from __future__ import annotations

from ...director.types import ShareComposePlan
from ...frame import PreparedComposeFrame
from ...guidance.share.candidates import format_share_candidates, select_share_candidates
from ...guidance.share.preview import format_share_preview
from ...guidance.share.state import ShareComposeState


def attach_share_to_frame(
    frame: PreparedComposeFrame,
    *,
    share_state: ShareComposeState,
    plan: ShareComposePlan,
) -> None:
    if not plan.include_preview:
        frame.guidance.share_preview = ""
        return
    if share_state.events:
        candidates = select_share_candidates(share_state.events)
        frame.guidance.share_preview = format_share_candidates(
            candidates,
            summary=share_state.summary,
        )
    else:
        frame.guidance.share_preview = format_share_preview(share_state)
    frame.wants_share = share_state.wants_share
    frame.share_summary = share_state.summary
