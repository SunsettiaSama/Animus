from __future__ import annotations

from dataclasses import dataclass
from random import Random

from ..ports.bm25 import Bm25Index
from ..ports.memory import MemoryUnit
from .staging import MemoryStagingBuffer, StagedMemory
from .utterance import is_noise_unit, match_query_from_utterances


@dataclass(frozen=True)
class RetrieveHit:
    unit: MemoryUnit
    score: float
    mode: str  # bm25 | random


class MemoryRetrievePolicy:
    """Stage-out：buffer 内 BM25 + 90/10 注入扰动。"""

    def __init__(
        self,
        staging: MemoryStagingBuffer,
        *,
        bm25: Bm25Index | None = None,
        rng: Random | None = None,
        normal_ratio: float = 0.90,
        min_score: float = 0.0,
        top_k: int = 3,
    ) -> None:
        self._staging = staging
        self._bm25 = bm25 or Bm25Index()
        self._rng = rng or Random()
        self._normal_ratio = min(1.0, max(0.0, normal_ratio))
        self._min_score = min_score
        self._top_k = max(1, top_k)

    def retrieve(
        self,
        session_id: str,
        *,
        primary_query: str,
        secondary_query: str = "",
    ) -> list[RetrieveHit]:
        # corpus：仅 staging 内具体输出（已在 ingest 过滤 system/persona）
        staged = [
            item
            for item in self._staging.items(session_id)
            if not is_noise_unit(item.unit, kind=item.kind)
        ]
        if not staged:
            return []
        roll = self._rng.random() * 100.0
        if roll >= self._normal_ratio * 100.0:
            picked = self._rng.choice(staged)
            return [RetrieveHit(unit=picked.unit, score=0.0, mode="random")]
        # query：只拼用户/角色/导演侧具体话语，不含 system/persona
        query = _compose_query(primary_query, secondary_query)
        if not query.strip():
            return []
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


def _compose_query(primary: str, secondary: str) -> str:
    primary = match_query_from_utterances(primary)
    secondary = match_query_from_utterances(secondary)
    if primary and secondary:
        # 当前轮为主：重复一次抬权重；过往为辅
        return match_query_from_utterances(primary, primary, secondary)
    return primary or secondary
