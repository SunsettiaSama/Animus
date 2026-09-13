from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.domain import MemoryTier, Valence
from agent.soul.memory.graph.base_node import BaseNode
from agent.soul.memory.graph.keywords import extract_keywords
from agent.soul.memory.graph.scored import ScoredUnit

from .node import StackMemoryUnit
from .store import StackMemoryStore


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


class StackRetrievalEngine:
    """栈式检索：自栈顶向栈底扫描，recency 衰减 × 关键词（可选语义）相关性。

    检索模式与 ``QueryEngine`` 同构（recent / semantic / by_valence /
    by_field / hybrid），返回 ``ScoredUnit``，因此可直接经
    ``scored_to_dict`` 形态输出，与 ``MemoryService.search`` 协议兼容。
    """

    def __init__(
        self,
        store: StackMemoryStore,
        *,
        half_life_days: float = 7.0,
        embedder=None,
    ) -> None:
        self._store = store
        self._half_life_days = half_life_days
        self._embedder = embedder  # callable(text) -> list[float] | []

    # ── scoring ────────────────────────────────────────────────────────────

    def _activation(self, unit: BaseNode, now: datetime) -> float:
        return unit.activation(now=now, half_life_days=self._half_life_days)

    @staticmethod
    def _unit_text(unit: StackMemoryUnit) -> str:
        return " ".join(part for part in (unit.focus, unit.content, " ".join(unit.tags)) if part).lower()

    @staticmethod
    def _cjk_chars(text: str) -> list[str]:
        return [c for c in text if "\u4e00" <= c <= "\u9fff"]

    @classmethod
    def _cjk_bigrams(cls, text: str) -> set[str]:
        chars = cls._cjk_chars(text)
        return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

    def _keyword_relevance(self, query: str, unit: StackMemoryUnit) -> float:
        hay = self._unit_text(unit)
        # 1) 分词命中（空格/标点分隔的关键词式查询）
        kws = [k for k in extract_keywords(query) if len(k) >= 2]
        token_score = 0.0
        if kws:
            token_score = sum(1 for k in kws if k in hay) / len(kws)
        # 2) 中文整句：字符 unigram + bigram 覆盖度（无分词器时的退化匹配）
        q_chars = self._cjk_chars(query)
        uni_score = 0.0
        if q_chars:
            hay_set = set(hay)
            uni_score = sum(1 for c in set(q_chars) if c in hay_set) / len(set(q_chars))
        q_bigrams = self._cjk_bigrams(query)
        bi_score = 0.0
        if q_bigrams:
            hay_bigrams = self._cjk_bigrams(hay)
            bi_score = sum(1 for bg in q_bigrams if bg in hay_bigrams) / len(q_bigrams)
        cjk_score = 0.6 * uni_score + 0.4 * bi_score
        return max(token_score, cjk_score)

    def _semantic_relevance(self, query: str, unit: StackMemoryUnit) -> float:
        if self._embedder is None:
            return 0.0
        qv = self._embedder(query)
        if not qv:
            return 0.0
        return max(0.0, _cosine(qv, self._embedder(unit.embed_text())))

    def _relevance(self, query: str, unit: StackMemoryUnit) -> float:
        kw = self._keyword_relevance(query, unit)
        sem = self._semantic_relevance(query, unit)
        if sem > 0.0:
            return max(kw, 0.5 * kw + 0.5 * sem)
        return kw

    # ── modes ──────────────────────────────────────────────────────────────

    def recent(
        self,
        limit: int = 10,
        memory_type: str | None = None,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        out: list[ScoredUnit] = []
        for unit in self._store.items():
            if memory_type and unit.MEMORY_TYPE != memory_type:
                continue
            act = self._activation(unit, now)
            out.append(ScoredUnit(unit, relevance=1.0, activation=act, final_score=act, source="stack"))
            if len(out) >= limit:
                break
        return out

    def semantic(self, query: str, top_k: int = 10) -> list[ScoredUnit]:
        if self._embedder is None:
            raise RuntimeError("semantic() requires an embedder; inject via stack embedder")
        now = datetime.now(timezone.utc)
        scored: list[ScoredUnit] = []
        for unit in self._store.items():
            rel = self._semantic_relevance(query, unit)
            act = self._activation(unit, now)
            scored.append(ScoredUnit(unit, relevance=rel, activation=act, final_score=rel * act, source="stack"))
        scored.sort(key=lambda s: s.final_score, reverse=True)
        return scored[:top_k]

    def by_valence(
        self,
        valence: Valence,
        limit: int = 10,
        emotion_hint: str = "",
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        hint = (emotion_hint or "").strip().lower()
        out: list[ScoredUnit] = []
        for unit in self._store.items():
            if unit.valence != valence:
                continue
            act = self._activation(unit, now)
            bonus = 0.1 if hint and hint in unit.emotion.lower() else 0.0
            out.append(ScoredUnit(unit, relevance=1.0, activation=act, final_score=act + bonus, source="stack"))
            if len(out) >= limit:
                break
        out.sort(key=lambda s: s.final_score, reverse=True)
        return out

    def by_field(
        self,
        *,
        memory_type: str | None = None,
        valence: Valence | None = None,
        emotion_contains: str | None = None,
        interactor_id: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 20,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)

        def _parse(value: str | None) -> datetime | None:
            if not value:
                return None
            try:
                dt = datetime.fromisoformat(str(value))
            except ValueError:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        after, before = _parse(created_after), _parse(created_before)
        needle = (emotion_contains or "").strip().lower()
        out: list[ScoredUnit] = []
        for unit in self._store.items():
            if memory_type and unit.MEMORY_TYPE != memory_type:
                continue
            if valence is not None and unit.valence != valence:
                continue
            if needle and needle not in unit.emotion.lower():
                continue
            if interactor_id and unit.interactor_id != interactor_id:
                continue
            if after and unit.created_at < after:
                continue
            if before and unit.created_at > before:
                continue
            act = self._activation(unit, now)
            out.append(ScoredUnit(unit, relevance=1.0, activation=act, final_score=act, source="stack"))
            if len(out) >= limit:
                break
        return out

    def hybrid(
        self,
        query: str,
        top_k: int = 5,
        *,
        valence: Valence | None = None,
        memory_type: str | None = None,
        interactor_id: str = "",
        w_relevance: float = 0.6,
        w_activation: float = 0.4,
        min_relevance: float = 0.10,
        fallback_recent: bool = True,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        scored: list[ScoredUnit] = []
        for unit in self._store.items():
            if valence is not None and unit.valence != valence:
                continue
            if memory_type and unit.MEMORY_TYPE != memory_type:
                continue
            if interactor_id and unit.interactor_id and unit.interactor_id != interactor_id:
                continue
            rel = self._relevance(query, unit)
            if rel < min_relevance:
                continue
            act = self._activation(unit, now)
            scored.append(ScoredUnit(
                unit,
                relevance=rel,
                activation=act,
                final_score=w_relevance * rel + w_activation * act,
                source="stack",
            ))
        if not scored:
            if fallback_recent:
                return self.recent(limit=top_k)
            return []
        scored.sort(key=lambda s: s.final_score, reverse=True)
        return scored[:top_k]

    def search(self, mode: str, **kwargs) -> list[ScoredUnit]:
        """与 ``MemoryService.search`` 相同的模式分派。"""
        m = mode.strip().lower()
        if m in ("recent", "timeline"):
            return self.recent(
                limit=int(kwargs.get("limit", kwargs.get("top_k", 10))),
                memory_type=kwargs.get("memory_type"),
            )
        if m == "semantic":
            return self.semantic(query=str(kwargs["query"]), top_k=int(kwargs.get("top_k", 10)))
        if m == "by_valence":
            return self.by_valence(
                valence=Valence(str(kwargs.get("valence", "neutral"))),
                limit=int(kwargs.get("limit", kwargs.get("top_k", 10))),
                emotion_hint=str(kwargs.get("emotion_hint", "")),
            )
        if m == "by_field":
            valence_raw = kwargs.get("valence")
            return self.by_field(
                memory_type=kwargs.get("memory_type"),
                valence=Valence(str(valence_raw)) if valence_raw else None,
                emotion_contains=kwargs.get("emotion_contains"),
                interactor_id=kwargs.get("interactor_id"),
                created_after=kwargs.get("created_after"),
                created_before=kwargs.get("created_before"),
                limit=int(kwargs.get("limit", 20)),
            )
        if m in ("hybrid", "smart", "recall"):
            valence_raw = kwargs.get("valence")
            return self.hybrid(
                query=str(kwargs.get("query", "")),
                top_k=int(kwargs.get("top_k", 5)),
                valence=Valence(str(valence_raw)) if valence_raw else None,
                memory_type=kwargs.get("memory_type"),
                interactor_id=str(kwargs.get("interactor_id") or ""),
                w_relevance=float(kwargs.get("w_relevance", 0.6)),
                w_activation=float(kwargs.get("w_activation", 0.4)),
            )
        raise ValueError(f"unknown stack memory search mode: {mode!r}")

    def record_recall(self, unit_ids: list[str]) -> None:
        wanted = set(unit_ids)
        dirty = False
        for unit in self._store.bottom_up():
            if unit.id in wanted:
                unit.on_recall()
                dirty = True
        if dirty:
            self._store.rewrite()
