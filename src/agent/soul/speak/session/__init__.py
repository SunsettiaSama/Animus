from .chunk import (
    ResolvedFeeling,
    SpeakFeelingChunk,
    SpeakSubjectiveChunk,
    SpeakTurnChunk,
    feeling_self_narration,
    resolve_feeling,
    resolve_subjective,
)
from .lifecycle import (
    SPEAK_SESSION_IDLE_SEC,
    CompositeSemanticBoundary,
    EmbeddingSemanticBoundary,
    SemanticSessionBoundary,
    SessionBootstrap,
    SessionEndReason,
    SessionEndResult,
    SessionHolder,
    SessionLifecyclePort,
    SessionOpenResult,
    SessionOpenTrigger,
    SessionStarter,
    SpeakSessionLifecycleAdapter,
    SpeakSessionRecord,
    SpeakSessionRegistry,
    TopicShiftSemanticBoundary,
    TurnRecordResult,
)
from .queue import (
    ComposeQueueItem,
    InterruptContext,
    QueueDecisionResult,
    QueueDecisionRunner,
    SessionComposeQueue,
    SessionQueueHub,
    SessionUserQueue,
    SubmitUserInputResult,
    UserInputItem,
)
from .service import SpeakSessionManager, SpeakSessionService
from .manage import SessionSocialManager

__all__ = [
    "ComposeQueueItem",
    "InterruptContext",
    "QueueDecisionResult",
    "QueueDecisionRunner",
    "ResolvedFeeling",
    "SPEAK_SESSION_IDLE_SEC",
    "CompositeSemanticBoundary",
    "EmbeddingSemanticBoundary",
    "SemanticSessionBoundary",
    "SessionBootstrap",
    "SessionComposeQueue",
    "SessionEndReason",
    "SessionEndResult",
    "SessionHolder",
    "SessionLifecyclePort",
    "SessionOpenResult",
    "SessionOpenTrigger",
    "SessionQueueHub",
    "SessionStarter",
    "SessionTurnHost",
    "SessionUserQueue",
    "SpeakFeelingChunk",
    "feeling_self_narration",
    "SpeakSessionLifecycleAdapter",
    "SessionSocialManager",
    "SpeakSessionManager",
    "SpeakSessionRecord",
    "SpeakSessionRegistry",
    "SpeakSessionService",
    "SpeakSubjectiveChunk",
    "SpeakTurnChunk",
    "SubmitUserInputResult",
    "TopicShiftSemanticBoundary",
    "TurnRecordResult",
    "UserInputItem",
    "resolve_feeling",
    "resolve_subjective",
]


def __getattr__(name: str):
    if name == "SessionTurnHost":
        from .turn import SessionTurnHost

        return SessionTurnHost
    if name == "run_session_turn":
        from .turn import run_session_turn

        return run_session_turn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
