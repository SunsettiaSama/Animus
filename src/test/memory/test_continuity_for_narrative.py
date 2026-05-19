from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.memory.retriever import MemoryRetriever, ScoredUnit


@dataclass
class _FakeUnit:
    id: str
    MEMORY_TYPE: str = "factual"
    focus: str = ""
    fact: str = ""
    reconstructed_fact: str = ""
    narrative: str = ""
    valence: object = field(default=None)

    def activation(self, *, now, half_life_days: float) -> float:
        return 0.5


def _scored(uid: str, rel: float, act: float = 0.4) -> ScoredUnit:
    u = _FakeUnit(id=uid, focus=f"f{uid}", fact=f"body{uid}")
    s = ScoredUnit(u, relevance=rel, activation=act, source="ltm")  # type: ignore[arg-type]
    s.final_score = 0.7 * rel + 0.3 * act
    return s


def test_continuity_empty_query():
    r = MemoryRetriever(stm=None, ltm=None)  # type: ignore[arg-type]
    assert r.continuity_for_narrative("") == []


def test_continuity_filters_by_min_relevance(monkeypatch):
    r = MemoryRetriever(stm=None, ltm=None)  # type: ignore[arg-type]
    r._embedder = object()
    r._vector_store = object()

    def fake_hybrid(query, top_k=5, **kwargs):
        return [
            _scored("a", 0.20),
            _scored("b", 0.18),
        ]

    monkeypatch.setattr(r, "hybrid", fake_hybrid)
    assert r.continuity_for_narrative("test", min_relevance=0.30) == []


def test_continuity_keeps_top_and_drops_large_gap(monkeypatch):
    r = MemoryRetriever(stm=None, ltm=None)  # type: ignore[arg-type]
    r._embedder = object()
    r._vector_store = object()

    def fake_hybrid(query, top_k=5, **kwargs):
        return [
            _scored("a", 0.80, act=0.5),
            _scored("b", 0.75, act=0.5),
            _scored("c", 0.40, act=0.3),
        ]

    monkeypatch.setattr(r, "hybrid", fake_hybrid)
    picked = r.continuity_for_narrative(
        "landmark intention",
        top_k=2,
        min_relevance=0.30,
        max_score_gap=0.20,
    )
    assert len(picked) == 2
    assert picked[0].unit.id == "a"
    assert picked[1].unit.id == "b"
