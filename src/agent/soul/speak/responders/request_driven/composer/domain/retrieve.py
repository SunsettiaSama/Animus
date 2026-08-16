from __future__ import annotations

import math
from dataclasses import dataclass
from random import Random

from ..ports.bm25 import Bm25Index
from ..ports.memory import BufferEmbedderPort, MemoryUnit, RetrieveMode
from .staging import MemoryStagingBuffer, StagedMemory
from .utterance import is_noise_unit, match_query_from_utterances


@dataclass(frozen=True)
class RetrieveHit:
    unit: MemoryUnit
    score: float
    mode: str  # bm25 | embedding | hybrid | random


class MemoryRetrievePolicy:
    """Stage-out：buffer 内 BM25 + embedding 向量检索 + 90/10 扰动。"""

    def __init__(
        self,
        staging: MemoryStagingBuffer,
        *,
        bm25: Bm25Index | None = None,
        rng: Random | None = None,
        embedder: BufferEmbedderPort | None = None,
        normal_ratio: float = 0.90,
        min_score: float = 0.0,
        top_k: int = 3,
        embedding_weight: float = 0.55,
        bm25_weight: float = 0.45,
    ) -> None:
        self._staging = staging
        self._bm25 = bm25 or Bm25Index()
        self._rng = rng or Random()
        self._embedder = embedder
        self._normal_ratio = min(1.0, max(0.0, normal_ratio))
        self._min_score = min_score
        self._top_k = max(1, top_k)
        self._embedding_weight = max(0.0, float(embedding_weight))
        self._bm25_weight = max(0.0, float(bm25_weight))

    def set_embedder(self, embedder: BufferEmbedderPort | None) -> None:
        self._embedder = embedder

    def retrieve(
        self,
        session_id: str,
        *,
        primary_query: str,
        secondary_query: str = "",
        mode: RetrieveMode = "hybrid",
    ) -> list[RetrieveHit]:
        staged = [
            item
            for item in self._staging.items(session_id)
            if not is_noise_unit(item.unit, kind=item.kind)
        ]
        if not staged:
            return []
        roll = self._rng.random() * 100.0
        if mode == "random" or roll >= self._normal_ratio * 100.0:
            picked = self._rng.choice(staged)
            return [RetrieveHit(unit=picked.unit, score=0.0, mode="random")]
        query = _compose_query(primary_query, secondary_query)
        if not query.strip():
            return []
        if mode == "bm25":
            return self._retrieve_bm25(staged, query)
        if mode == "embedding":
            return self._retrieve_embedding(staged, query)
        return self._retrieve_hybrid(staged, query)

    def _retrieve_bm25(self, staged: list[StagedMemory], query: str) -> list[RetrieveHit]:
        self._bm25.build([(item.unit.unit_id, item.unit.text) for item in staged])
        scored = self._bm25.score(query, min_score=self._min_score, top_k=self._top_k)
        by_id = {item.unit.unit_id: item for item in staged}
        hits: list[RetrieveHit] = []
        for unit_id, score in scored:
            item = by_id.get(unit_id)
            if item is None:
                continue
            hits.append(RetrieveHit(unit=item.unit, score=score, mode="bm25"))
        return hits

    def _retrieve_embedding(self, staged: list[StagedMemory], query: str) -> list[RetrieveHit]:
        q_vec = self._query_vector(query)
        if not q_vec:
            return self._retrieve_bm25(staged, query)
        scored: list[tuple[StagedMemory, float]] = []
        for item in staged:
            vec = item.unit.embedding
            if not vec:
                continue
            sim = _cosine(q_vec, vec)
            if sim >= self._min_score:
                scored.append((item, sim))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            RetrieveHit(unit=item.unit, score=score, mode="embedding")
            for item, score in scored[: self._top_k]
        ]

    def _retrieve_hybrid(self, staged: list[StagedMemory], query: str) -> list[RetrieveHit]:
        bm25_hits = {hit.unit.unit_id: hit.score for hit in self._retrieve_bm25(staged, query)}
        emb_hits = {hit.unit.unit_id: hit.score for hit in self._retrieve_embedding(staged, query)}
        if not bm25_hits and not emb_hits:
            return []
        max_bm25 = max(bm25_hits.values()) if bm25_hits else 1.0
        max_emb = max(emb_hits.values()) if emb_hits else 1.0
        by_id = {item.unit.unit_id: item for item in staged}
        combined: list[RetrieveHit] = []
        for uid in set(bm25_hits) | set(emb_hits):
            item = by_id.get(uid)
            if item is None:
                continue
            b = (bm25_hits.get(uid, 0.0) / max_bm25) if max_bm25 > 0 else 0.0
            e = (emb_hits.get(uid, 0.0) / max_emb) if max_emb > 0 else 0.0
            if not emb_hits:
                score = b
            elif not bm25_hits:
                score = e
            else:
                score = self._bm25_weight * b + self._embedding_weight * e
            if score < self._min_score:
                continue
            combined.append(RetrieveHit(unit=item.unit, score=score, mode="hybrid"))
        combined.sort(key=lambda hit: hit.score, reverse=True)
        return combined[: self._top_k]

    def _query_vector(self, query: str) -> tuple[float, ...] | None:
        if self._embedder is None:
            return None
        vector = self._embedder.embed(query)
        if not vector:
            return None
        return tuple(float(x) for x in vector)


def _compose_query(primary: str, secondary: str) -> str:
    primary = match_query_from_utterances(primary)
    secondary = match_query_from_utterances(secondary)
    if primary and secondary:
        return match_query_from_utterances(primary, primary, secondary)
    return primary or secondary


def _cosine(a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        na += fx * fx
        nb += fy * fy
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
