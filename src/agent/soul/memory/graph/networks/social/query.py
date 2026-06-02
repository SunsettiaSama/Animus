from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.domain.enums import MemoryNetwork, MemoryTier
from agent.soul.memory.embed_text import cosine_similarity
from agent.soul.memory.graph.scored import ScoredUnit
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.ports import VectorIndexPort

from .time_weight import event_time_weight


class SocialQueryEngine:
    """Social 网络混合检索：向量相似度 + 激活衰减。"""

    def __init__(
        self,
        nodes: GraphNodeStore,
        *,
        half_life_days: float = 30.0,
        event_time_half_life_days: float = 60.0,
        vectors: VectorIndexPort | None = None,
        w_relevance: float = 0.6,
        w_activation: float = 0.4,
    ) -> None:
        self._nodes = nodes
        self._hl = half_life_days
        self._event_time_hl = event_time_half_life_days
        self._vectors = vectors
        self._w_relevance = w_relevance
        self._w_activation = w_activation

    def hybrid(
        self,
        query: str,
        top_k: int = 5,
        *,
        interactor_id: str = "",
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        candidates: list[ScoredUnit] = []
        if self._vectors is not None and query.strip():
            vector = self._vectors.embed_query(query)
            if vector:
                hits = self._vectors.search(vector, top_k=top_k * 4, network=MemoryNetwork.social)
                id_score = {uid: score for uid, score in hits}
                for unit in self._nodes.get_many(list(id_score.keys())):
                    if interactor_id and unit.interactor_id and unit.interactor_id != interactor_id:
                        continue
                    act = self._activation(unit, now)
                    rel = id_score.get(unit.id, 0.0)
                    candidates.append(ScoredUnit(unit, relevance=rel, activation=act))
        if not candidates:
            pool = self._nodes.list_by_network(MemoryNetwork.social, limit=top_k * 6)
            if interactor_id:
                pool = [u for u in pool if u.interactor_id == interactor_id]
            for unit in pool:
                act = self._activation(unit, now)
                rel = self._text_overlap(query, unit.embed_text())
                candidates.append(ScoredUnit(unit, relevance=rel, activation=act))
        self._apply_final_scores(candidates, now)
        candidates.sort(key=lambda s: s.final_score, reverse=True)
        return candidates[:top_k]

    def hybrid_with_stored_embeddings(
        self,
        query: str,
        top_k: int = 5,
        *,
        interactor_id: str = "",
    ) -> list[ScoredUnit]:
        """无在线向量服务时，回退到节点持久化的 embedding_json。"""
        now = datetime.now(timezone.utc)
        pool = self._nodes.list_by_network(MemoryNetwork.social, limit=500)
        if interactor_id:
            pool = [u for u in pool if u.interactor_id == interactor_id]
        query_vector: list[float] = []
        if self._vectors is not None and query.strip():
            query_vector = self._vectors.embed_query(query)
        candidates: list[ScoredUnit] = []
        for unit in pool:
            rel = 0.0
            stored = getattr(unit, "embedding", None) or []
            if query_vector and stored:
                rel = cosine_similarity(query_vector, stored)
            elif query.strip():
                rel = self._text_overlap(query, unit.embed_text())
            else:
                rel = 1.0
            act = self._activation(unit, now)
            candidates.append(ScoredUnit(unit, relevance=rel, activation=act))
        self._apply_final_scores(candidates, now)
        candidates.sort(key=lambda s: s.final_score, reverse=True)
        return candidates[:top_k]

    def recall(
        self,
        query: str,
        top_k: int = 5,
        *,
        interactor_id: str = "",
    ) -> list[ScoredUnit]:
        if self._vectors is not None and self._vectors.embed_query(query.strip()):
            return self.hybrid(query, top_k, interactor_id=interactor_id)
        return self.hybrid_with_stored_embeddings(query, top_k, interactor_id=interactor_id)

    def _apply_final_scores(self, candidates: list[ScoredUnit], now: datetime) -> None:
        for scored in candidates:
            base = (
                self._w_relevance * scored.relevance
                + self._w_activation * scored.activation
            )
            tw = event_time_weight(
                scored.unit,
                now,
                half_life_days=self._event_time_hl,
            )
            scored.final_score = base * tw

    def _activation(self, unit, now: datetime) -> float:
        hl = self._hl if unit.tier != MemoryTier.short_term else 3.0
        return unit.activation(now=now, half_life_days=hl)

    @staticmethod
    def _text_overlap(query: str, haystack: str) -> float:
        q = query.strip().lower()
        if not q:
            return 1.0
        text = haystack.lower()
        hits = sum(1 for token in q.split() if token and token in text)
        return min(1.0, hits / max(1, len(q.split())))
