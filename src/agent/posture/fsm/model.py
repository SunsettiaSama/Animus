from __future__ import annotations

from agent.posture.events import InteractionEventKind

TERMINATING_EVENT_KINDS = frozenset(
    {
        InteractionEventKind.close,
        InteractionEventKind.idle_timeout,
        InteractionEventKind.continuity_break,
    }
)
