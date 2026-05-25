"""interface 共享类型（无 FSM / service 依赖，供 ingress 与 fsm 共用）。"""

from .events import EVOLUTION_KINDS, CaptureEvent, CaptureKind
from .hint import default_share_desire, evolution_hint, parse_event_share_desire

__all__ = [
    "CaptureEvent",
    "CaptureKind",
    "EVOLUTION_KINDS",
    "default_share_desire",
    "evolution_hint",
    "parse_event_share_desire",
]
