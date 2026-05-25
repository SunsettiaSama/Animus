"""状态转移：期待 FSM、FSM 初始化（起床/休眠）、用户-agent 会话刷新、边界事件 ingest。"""

from .apply import TransitionResult, apply_presence_transition, apply_transition
from .engine import PresenceTransitionEngine, PresenceTransitionOutcome
from .trigger import PresenceTrigger, PresenceTriggerKind
from .dialogue import (
    DIALOGUE_FSM_REFRESH_EVERY_K,
    DialogueBlock,
    DialogueExperience,
    DialogueFsmRefresher,
    DialogueObserveResult,
    DialogueRefreshResult,
    DialogueSessionTransition,
)
from .incident import (
    IncidentFsmRefresher,
    IncidentIngestResult,
    IncidentKind,
    IncidentTransition,
    LifeIncident,
)
from .rumination import (
    RuminationFsmRefresher,
    RuminationIngestResult,
    RuminationSignal,
    RuminationTransition,
)
from .edges import PRESENCE_EDGES, match_presence_edge
from .expectation import Expectation
from .init import (
    PresenceWakeEngine,
    SleepResult,
    WakeContext,
    WakeResult,
    apply_sleep,
)
from .interaction import PresenceInteraction

__all__ = [
    "DIALOGUE_FSM_REFRESH_EVERY_K",
    "PRESENCE_EDGES",
    "PresenceTransitionEngine",
    "PresenceTransitionOutcome",
    "PresenceTrigger",
    "PresenceTriggerKind",
    "DialogueBlock",
    "DialogueExperience",
    "DialogueFsmRefresher",
    "DialogueObserveResult",
    "DialogueRefreshResult",
    "DialogueSessionTransition",
    "IncidentFsmRefresher",
    "IncidentIngestResult",
    "IncidentKind",
    "IncidentTransition",
    "LifeIncident",
    "RuminationFsmRefresher",
    "RuminationIngestResult",
    "RuminationSignal",
    "RuminationTransition",
    "Expectation",
    "PresenceInteraction",
    "PresenceWakeEngine",
    "SleepResult",
    "TransitionResult",
    "WakeContext",
    "WakeResult",
    "apply_presence_transition",
    "apply_sleep",
    "apply_transition",
    "match_presence_edge",
]
