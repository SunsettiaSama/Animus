"""interface 出站：冲动门控 → SpeakRequest + react 执行。"""

from .gate import SpeakInterface, SpeakInterfaceConfig
from .package import (
    ShareFoldedPackage,
    enqueue_capture_event,
    enqueue_share_event,
    fold_share_buffer,
    fold_share_queue,
    share_intent_from_capture,
)
from .request import SpeakRequest
from .react import (
    EmbeddingPort,
    LightweightReactEngine,
    PresenceReactOutbound,
    ReactAction,
    ReactActionCall,
    ReactActionExecutor,
    ReactStepResult,
    parse_action_field,
)

__all__ = [
    "EmbeddingPort",
    "LightweightReactEngine",
    "PresenceReactOutbound",
    "ReactAction",
    "ReactActionCall",
    "ReactActionExecutor",
    "ReactStepResult",
    "ShareFoldedPackage",
    "SpeakInterface",
    "SpeakInterfaceConfig",
    "SpeakRequest",
    "enqueue_capture_event",
    "enqueue_share_event",
    "fold_share_buffer",
    "fold_share_queue",
    "parse_action_field",
    "share_intent_from_capture",
]
