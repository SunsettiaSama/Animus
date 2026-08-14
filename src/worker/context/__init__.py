"""Worker context timeline + legacy step/memory processor."""
from __future__ import annotations

from worker.context.timeline import ContextTimeline
from worker.context.unit import ContextUnit, UnitKind, UnitPriority

__all__ = [
    "ContextTimeline",
    "ContextUnit",
    "UnitKind",
    "UnitPriority",
    "Memory",
    "Step",
    "RecentHistoryMemory",
    "MemoryProcessor",
    "MemoryResult",
]


def __getattr__(name: str):
    if name in {"Memory", "Step"}:
        from worker.context.memory import Memory, Step

        return Memory if name == "Memory" else Step
    if name == "RecentHistoryMemory":
        from worker.context.medium_term.memory import RecentHistoryMemory

        return RecentHistoryMemory
    if name in {"MemoryProcessor", "MemoryResult"}:
        from worker.context.processor import MemoryProcessor, MemoryResult

        return MemoryProcessor if name == "MemoryProcessor" else MemoryResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
