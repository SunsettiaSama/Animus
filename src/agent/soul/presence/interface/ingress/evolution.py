from __future__ import annotations

from config.soul.presence.config import REPLY_URGE_BY_DESIRE_WEIGHT

from ...fsm.state import PresenceState
from ...share_desire import max_share_desire, share_desire_weight
from ...transition.interaction import PresenceInteraction
from ..shared.events import CaptureEvent
from ..shared.hint import evolution_hint, parse_event_share_desire


def apply_evolution_impulse(
    interaction: PresenceInteraction,
    event: CaptureEvent,
    *,
    state: PresenceState | None = None,
) -> str:
    """演化入站 → 按 share_desire 累积冲动，并同步 FSM 期待驱动。"""
    desire = parse_event_share_desire(event)
    weight = share_desire_weight(desire)
    source = str(event.payload.get("source", event.kind.value))
    hint = evolution_hint(event)
    interaction.impulse_level = min(1.0, interaction.impulse_level + max(0.0, weight))
    interaction.share_desire = max_share_desire(interaction.share_desire, desire)
    interaction.impulse_source = source
    if hint:
        interaction.impulse_reason = hint
    if state is not None:
        state.expectation.accumulate_toward_user(
            weight,
            reason=hint,
            source=source,
        )
        reply_delta = REPLY_URGE_BY_DESIRE_WEIGHT[desire.value]
        if reply_delta > 0.0:
            state.expectation.accumulate_reply_urge(
                reply_delta,
                reason=hint,
                source=source,
            )
    return f"evolution captured: {event.kind.value} share={desire.value}"
