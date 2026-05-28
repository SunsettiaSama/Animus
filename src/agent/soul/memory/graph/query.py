from __future__ import annotations

import random
from datetime import datetime, timezone

from agent.soul.memory.domain import MemoryNetwork, MemoryTier, Valence
from agent.soul.memory.graph.scored import ScoredUnit
from agent.soul.memory.ports import GraphNodeStore, VectorIndexPort


class QueryEngine:
    """事件网络检索（L3）：hybrid / recent / semantic 等，不含扩散激活。"""

    def __init__(
        self,
        nodes: GraphNodeStore,
        *,
        recent_half_life_days: float = 3.0,
        half_life_days: float = 30.0,
        vectors: VectorIndexPort | None = None,
    ) -> None:
        self._nodes = nodes
        self._recent_hl = recent_half_life_days
        self._hl = half_life_days
        self._vectors = vectors

    def _activation(self, unit, now: datetime) -> float:
        hl = self._recent_hl if unit.tier == MemoryTier.short_term else self._hl
        return unit.activation(now=now, half_life_days=hl)

    def recent(
        self,
        limit: int = 10,
        memory_type: str | None = None,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        units = self._nodes.list_recent(
            memory_type=memory_type,
            network=MemoryNetwork.event,
            limit=limit,
        )
        results = [
            ScoredUnit(u, activation=self._activation(u, now), final_score=self._activation(u, now))
            for u in units
        ]
        results.sort(key=lambda s: s.unit.last_accessed, reverse=True)
        return results[:limit]

    def semantic(self, query: str, top_k: int = 10) -> list[ScoredUnit]:
        if self._vectors is None:
            raise RuntimeError("semantic() 需要 VectorIndexPort")
        now = datetime.now(timezone.utc)
        vector = self._vectors.embed_query(query)
        hits = self._vectors.search(vector, top_k=top_k, network=MemoryNetwork.event)
        score_map = {uid: score for uid, score in hits}
        results: list[ScoredUnit] = []
        for u in self._nodes.get_many(list(score_map.keys())):
            rel = score_map.get(u.id, 0.0)
            act = self._activation(u, now)
            results.append(ScoredUnit(u, relevance=rel, activation=act, final_score=rel * act))
        results.sort(key=lambda s: s.final_score, reverse=True)
        return results

    def hybrid(
        self,
        query: str,
        top_k: int = 5,
        valence: Valence | None = None,
        memory_type: str | None = None,
        w_relevance: float = 0.6,
        w_activation: float = 0.4,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        candidates: list[ScoredUnit] = []
        if self._vectors is not None and query.strip():
            vector = self._vectors.embed_query(query)
            hits = self._vectors.search(vector, top_k=top_k * 3, network=MemoryNetwork.event)
            id_score = {uid: score for uid, score in hits}
            for u in self._nodes.get_many(list(id_score.keys())):
                act = self._activation(u, now)
                rel = id_score.get(u.id, 0.0)
                candidates.append(ScoredUnit(u, relevance=rel, activation=act))
        if not candidates:
            for u in self._nodes.list_recent(limit=top_k * 2, network=MemoryNetwork.event):
                act = self._activation(u, now)
                candidates.append(ScoredUnit(u, relevance=1.0, activation=act))
        if valence is not None:
            candidates = [s for s in candidates if s.unit.valence == valence]
        if memory_type is not None:
            candidates = [s for s in candidates if s.unit.MEMORY_TYPE == memory_type]
        for s in candidates:
            s.final_score = w_relevance * s.relevance + w_activation * s.activation
        candidates.sort(key=lambda s: s.final_score, reverse=True)
        return candidates[:top_k]

    def wander(
        self,
        n: int = 1,
        focus_keywords: list[str] | None = None,
        keyword_boost: float = 0.28,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        pool = self._nodes.list_recent(limit=80, network=MemoryNetwork.event)
        if not pool:
            return []
        scored: list[ScoredUnit] = []
        for u in pool:
            act = self._activation(u, now)
            raw = act + random.random() * 0.15
            if focus_keywords:
                hay = f"{u.focus} {getattr(u, 'fact', '')}".lower()
                if any(k.strip() and k.strip().lower() in hay for k in focus_keywords):
                    raw += keyword_boost
            scored.append(ScoredUnit(u, activation=act, final_score=min(1.0, raw)))
        scored.sort(key=lambda s: s.final_score, reverse=True)
        return scored[:n]
