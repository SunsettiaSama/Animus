from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.soul.memory.graph.field_keyword import FieldKeywordQueryEngine


@dataclass
class _FakeUnit:
    id: str
    focus: str = ""
    fact: str = ""
    emotion: str = ""
    interactor_id: str = ""
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class _FakeNodeStore:
    def __init__(self, units: list[_FakeUnit]) -> None:
        self._units = units

    def list_recent(self, *, limit: int, network):
        _ = network
        return self._units[:limit]


def test_field_keyword_matches_focus_substring():
    store = _FakeNodeStore(
        [
            _FakeUnit(id="u1", focus="荧光孢子森林"),
            _FakeUnit(id="u2", focus="无关内容"),
        ]
    )
    engine = FieldKeywordQueryEngine(store)
    scored = engine.query("荧光孢子", top_k=3)
    assert [s.unit.id for s in scored] == ["u1"]


def test_field_keyword_empty_text_returns_empty():
    store = _FakeNodeStore([_FakeUnit(id="u1", focus="测试")])
    engine = FieldKeywordQueryEngine(store)
    assert engine.query("   ", top_k=3) == []
