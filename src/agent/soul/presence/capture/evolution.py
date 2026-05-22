from __future__ import annotations

from ..fsm.events import DriveEvent, DriveEventKind
from .events import BOUNDARY_KINDS, CaptureEvent, CaptureKind


def capture_event_from_drive(event: DriveEvent) -> CaptureEvent:
    kind = CaptureKind(event.kind.value)
    return CaptureEvent(kind=kind, session_id=event.session_id, payload=dict(event.payload))


def drive_event_from_capture(event: CaptureEvent) -> DriveEvent:
    if event.kind not in BOUNDARY_KINDS:
        raise ValueError(f"not a boundary capture event: {event.kind.value}")
    return DriveEvent(
        DriveEventKind(event.kind.value),
        event.session_id,
        dict(event.payload),
    )


def capture_event_from_wander(
    _result: object,
    *,
    session_id: str = "tao",
) -> CaptureEvent | None:
    """禁用客观信号直推：wander 仅通过 life 主观 story beats 上报。"""
    _ = session_id
    return None
