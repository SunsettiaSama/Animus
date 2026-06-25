from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent

from .reveal import ShareRevealResult, render_share_full_text
from .state import ShareEventView

if TYPE_CHECKING:
    from collections.abc import Callable

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
    *,
    pop_deferred: Callable[[str], ShareIntent | None] | None = None,
) -> ShareRevealResult:
    """pop 最想分享的一条；优先消费 speak 活跃会话延迟注入队列。"""
    if pop_deferred is not None:
        deferred = pop_deferred(session_id)
        if deferred is not None:
            event = intent_to_event_view(deferred)
            return ShareRevealResult(
                ok=True,
                pointer="pop",
                full_text=render_share_full_text(event),
                event=event,
                trigger_source="state:share",
            )
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
