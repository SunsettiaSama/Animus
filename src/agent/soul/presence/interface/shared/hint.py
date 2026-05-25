from __future__ import annotations

from ...share_desire import ShareDesire, parse_share_desire, share_desire_from_intensity
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


def parse_event_share_desire(event: CaptureEvent) -> ShareDesire:
    return parse_share_desire(
        event.payload.get("share_desire"),
        default=default_share_desire(event),
    )
