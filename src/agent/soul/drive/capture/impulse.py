from __future__ import annotations

from ..fsm.state import DriveState
from ..share_desire import (
    ShareDesire,
    max_share_desire,
    parse_share_desire,
    share_desire_from_intensity,
    share_desire_weight,
)
from .events import CaptureEvent, CaptureKind


def default_share_desire(event: CaptureEvent) -> ShareDesire:
    if event.kind == CaptureKind.landmark:
        return ShareDesire.none
    if event.kind == CaptureKind.surprise:
        return ShareDesire.eager
    if event.kind in (CaptureKind.wander, CaptureKind.story_beat):
        intensity = float(event.payload.get("salience", 0.0))
        return share_desire_from_intensity(intensity)
    return ShareDesire.mild


def evolution_hint(event: CaptureEvent) -> str:
    payload = event.payload
    if event.kind == CaptureKind.landmark:
        intention = str(payload.get("intention", "")).strip()
        context = str(payload.get("context", "")).strip()
        if context:
            return f"{intention}（{context}）"
        return intention
    return str(payload.get("hint", "")).strip()


def apply_evolution_impulse(state: DriveState, event: CaptureEvent) -> str:
    """Soul 内部演化 → 按 share_desire 软分层累积冲动。"""
    desire = parse_share_desire(
        event.payload.get("share_desire"),
        default=default_share_desire(event),
    )
    weight = share_desire_weight(desire)
    source = str(event.payload.get("source", event.kind.value))
    hint = evolution_hint(event)
    state.impulse_level = min(1.0, state.impulse_level + max(0.0, weight))
    state.share_desire = max_share_desire(state.share_desire, desire)
    state.impulse_source = source
    if hint:
        state.impulse_reason = hint
    return f"evolution captured: {event.kind.value} share={desire.value}"
