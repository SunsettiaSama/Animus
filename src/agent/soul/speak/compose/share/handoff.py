from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent

from .reveal import ShareRevealResult, render_share_full_text
from .state import ShareEventView

if TYPE_CHECKING:
    from agent.soul.presence import PresenceService


def intent_to_event_view(intent: ShareIntent) -> ShareEventView:
    return ShareEventView(
        index=0,
        topic=intent.topic,
        share_desire=intent.share_desire,
        source=intent.source,
        salience=intent.salience,
        brief=intent.topic.strip(),
    )


def pop_share_handoff(
    presence: PresenceService,
    session_id: str,
) -> ShareRevealResult:
    """pop 最想分享的一条，并渲染完整摘要交给 agent。"""
    intent = presence.pop_share_intent(session_id)
    if intent is None:
        return ShareRevealResult(
            ok=False,
            pointer="pop",
            reason="share queue empty",
        )
    event = intent_to_event_view(intent)
    return ShareRevealResult(
        ok=True,
        pointer="pop",
        full_text=render_share_full_text(event),
        event=event,
        trigger_source="state:share",
    )
