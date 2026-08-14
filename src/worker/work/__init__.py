"""worker.work — Speak→Worker lightweight task intent & execution bridge."""

from worker.work.matcher import WorkIntentMatcher, MatchResult, DEFAULT_TASK_VERBS
from worker.work.service import WorkerWorkService, WorkTransitionError
from worker.work.types import (
    WorkDecision,
    WorkEvent,
    WorkIntentSignal,
    WorkRecord,
    WorkStatus,
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
)
from worker.work.adapter import WorkerAdapter, WorkerAdapterConfig

__all__ = [
    "WorkIntentMatcher",
    "MatchResult",
    "DEFAULT_TASK_VERBS",
    "WorkerWorkService",
    "WorkTransitionError",
    "WorkDecision",
    "WorkEvent",
    "WorkIntentSignal",
    "WorkRecord",
    "WorkStatus",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "WorkerAdapter",
    "WorkerAdapterConfig",
]
