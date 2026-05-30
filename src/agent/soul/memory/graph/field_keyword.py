from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.domain.enums import MemoryNetwork
from agent.soul.memory.graph.keywords import extract_keywords
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.graph.scored import ScoredUnit


def _activation(unit, now: datetime, *, half_life_days: float) -> float:
    accessed = unit.last_accessed
    if accessed.tzinfo is None:
        accessed = accessed.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - accessed).total_seconds() / 86400.0)
    import math

    return math.exp(-math.log(2) * age_days / max(half_life_days, 0.1))


def _haystack(unit) -> str:
    parts = [
        str(getattr(unit, "focus", "") or ""),
        str(getattr(unit, "fact", "") or ""),
        str(getattr(unit, "emotion", "") or ""),
    ]
    return " ".join(parts).lower()


class FieldKeywordQueryEngine:
    """Speak 专用粗粒度关键字检索（Event 网 recent pool + 子串命中）。"""

    def __init__(
        self,
        nodes: GraphNodeStore,
        *,
        half_life_days: float = 3.0,
        pool_limit: int = 80,
    ) -> None:
        self._nodes = nodes
        self._half_life_days = half_life_days
        self._pool_limit = pool_limit

    def query(
        self,
        text: str,
        *,
        interactor_id: str = "",
        top_k: int = 5,
    ) -> list[ScoredUnit]:
        keywords = extract_keywords(text)
        if not keywords:
            return []

        now = datetime.now(timezone.utc)
        pool = self._nodes.list_recent(
            limit=self._pool_limit,
            network=MemoryNetwork.event,
        )
        ranked: list[ScoredUnit] = []
        for unit in pool:
            if interactor_id and unit.interactor_id and unit.interactor_id != interactor_id:
                continue
            hay = _haystack(unit)
            hits = sum(1 for kw in keywords if kw in hay)
            if hits <= 0:
                continue
            act = _activation(unit, now, half_life_days=self._half_life_days)
            score = min(1.0, 0.35 * hits + 0.65 * act)
            ranked.append(
                ScoredUnit(
                    unit,
                    relevance=float(hits) / len(keywords),
                    activation=act,
                    final_score=score,
                    source="keyword",
                )
            )
        ranked.sort(key=lambda s: s.final_score, reverse=True)
        return ranked[:top_k]
