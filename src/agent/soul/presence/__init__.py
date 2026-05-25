from .interface import CaptureEvent, SpeakRequest
from .block import PresenceAffectBlock, PresenceBlock
from .expectation import Expectation
from .fsm import (
    ExpectationState,
    PresenceContext,
    PresenceEvent,
    PresenceEventKind,
    PresenceState,
    PROACTIVE_OPEN_THRESHOLD,
    REPLY_URGE_THRESHOLD,
)
from .fsm.affect import AffectState
from .service import (
    PresenceIngestResult,
    PresenceLayer,
    PresenceService,
    PresenceSnapshot,
    PresenceTransitionResult,
    capture_event_from_presence,
    capture_event_from_wander,
)
from .interface import PresenceInterface, PresenceTriggerResult
from .share_desire import ShareDesire, share_desire_weight
from .store import PresenceStateStore, StoredPresenceSession
from .transition import (
    IncidentIngestResult,
    IncidentKind,
    LifeIncident,
    PresenceTransitionEngine,
    PresenceTransitionOutcome,
    PresenceTrigger,
    PresenceTriggerKind,
)
from .experience import (
    DialogueExperiencePipeline,
    PresenceExperiencePipeline,
)

# 兼容旧名
from .interface import SpeakInterface, SpeakInterfaceConfig

PresenceGate = SpeakInterface
PresenceGateConfig = SpeakInterfaceConfig
PresenceOutboundRequest = SpeakRequest

__all__ = [
    "AffectState",
    "CaptureEvent",
    "Expectation",
    "ExpectationState",
    "IncidentIngestResult",
    "IncidentKind",
    "LifeIncident",
    "DialogueExperiencePipeline",
    "PresenceExperiencePipeline",
    "PresenceContext",
    "PresenceEvent",
    "PresenceEventKind",
    "PresenceIngestResult",
    "PresenceInterface",
    "PresenceLayer",
    "PresenceService",
    "PresenceSnapshot",
    "PresenceState",
    "PresenceTransitionResult",
    "PresenceTransitionEngine",
    "PresenceTransitionOutcome",
    "PresenceTrigger",
    "PresenceTriggerKind",
    "PresenceTriggerResult",
    "PROACTIVE_OPEN_THRESHOLD",
    "REPLY_URGE_THRESHOLD",
    "PresenceAffectBlock",
    "PresenceBlock",
    "PresenceStateStore",
    "SpeakRequest",
    "StoredPresenceSession",
    "ShareDesire",
    "share_desire_weight",
    "capture_event_from_presence",
    "capture_event_from_wander",
]
