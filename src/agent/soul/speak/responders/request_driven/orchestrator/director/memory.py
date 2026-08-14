from __future__ import annotations

from ..blocks.memory import (
    build_memory_inject_plan,
    has_topic_shift_signal,
    is_short_ack,
    kick_memory_requests,
)

apply_memory_requests = kick_memory_requests

__all__ = [
    "apply_memory_requests",
    "build_memory_inject_plan",
    "has_topic_shift_signal",
    "is_short_ack",
    "kick_memory_requests",
]
