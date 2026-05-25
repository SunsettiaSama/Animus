from __future__ import annotations

from agent.soul.presence.interface.shared.hint import default_share_desire, evolution_hint
from agent.soul.presence.interface.shared.events import CaptureEvent
from agent.soul.presence.share_desire import ShareDesire, parse_share_desire

from .queue import ShareIntent
from .state import ExpectationState


def share_intent_from_capture(event: CaptureEvent) -> ShareIntent | None:
    desire = parse_share_desire(
        event.payload.get("share_desire"),
        default=default_share_desire(event),
    )
    if desire == ShareDesire.none:
        return None
    topic = evolution_hint(event)
    if not topic.strip():
        return None
    payload = event.payload
    return ShareIntent(
        topic=topic,
        share_desire=desire,
        source=str(payload.get("source", event.kind.value)),
        salience=float(payload.get("salience", 0.0)),
    )


def enqueue_capture_event(expectation: ExpectationState, event: CaptureEvent) -> bool:
    intent = share_intent_from_capture(event)
    if intent is None:
        return False
    expectation.share_queue.enqueue(intent)
    return True
