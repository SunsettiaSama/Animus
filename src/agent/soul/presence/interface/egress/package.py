from __future__ import annotations

from agent.soul.presence.fsm.expectation.capture import (
    enqueue_capture_event,
    share_intent_from_capture,
)
from agent.soul.presence.fsm.expectation.package import ShareFoldedPackage, fold_share_queue

enqueue_share_event = enqueue_capture_event
fold_share_buffer = fold_share_queue

__all__ = [
    "ShareFoldedPackage",
    "enqueue_capture_event",
    "enqueue_share_event",
    "fold_share_buffer",
    "fold_share_queue",
    "share_intent_from_capture",
]
