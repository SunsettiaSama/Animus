from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.domain import MemoryTier, Valence
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.graph.scored import ScoredUnit


class _Unit:
    MEMORY_TYPE = "factual"

    def __init__(self, interactor_id: str) -> None:
        self.interactor_id = interactor_id
        self.last_accessed = datetime.now(timezone.utc)
        self.tier = MemoryTier.long
        self.valence = Valence.neutral
        self.focus = "test"


def _scored(iid: str) -> ScoredUnit:
    return ScoredUnit(_Unit(iid))


def test_event_relaxed_keeps_empty_interactor():
    rows = [
        _scored("user-a"),
        _scored(""),
        _scored("user-b"),
    ]
    out = QueryEngine._filter_interactor_relaxed(rows, "user-a")
    ids = [(getattr(s.unit, "interactor_id", "") or "") for s in out]
    assert "" in ids
    assert "user-a" in ids
    assert "user-b" not in ids


def test_event_strict_excludes_empty():
    rows = [_scored("user-a"), _scored("")]
    out = QueryEngine._filter_interactor(rows, "user-a")
    assert len(out) == 1
    assert out[0].unit.interactor_id == "user-a"
