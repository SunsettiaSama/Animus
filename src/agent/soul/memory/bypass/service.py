from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent.soul.memory.graph.networks.block import MemoryBlock
from agent.soul.memory.graph.scored import ScoredUnit

from .node import StackMemoryUnit
from .retrieval import StackRetrievalEngine
from .store import StackMemoryStore

DEFAULT_STACK_FILENAME = "bypass/stack_memory.jsonl"


class StackMemoryService:
    """增量式 stack 记忆旁路。

    语义边界：
    - 与 event/social 双网**完全隔离**——独立存储、独立检索，
      不进共享 node/edge store，不参与扩散激活/聚类/反刍/睡眠；
    - 追加式写入（push 即落盘），自栈顶向栈底做 recency 衰减检索；
    - 对外只讲 ``MemoryBasePort`` 的语言（ingest / recall / search），
      因此可作为 graph 基座的可替换项接入 Speak 或 benchmark。
    """

    def __init__(
        self,
        path: str | Path = "",
        *,
        max_entries: int = 2000,
        half_life_days: float = 7.0,
        embedder: Callable[[str], list[float]] | None = None,
        store: StackMemoryStore | None = None,
    ) -> None:
        self._store = store or StackMemoryStore(path, max_entries=max_entries)
        self._engine = StackRetrievalEngine(
            self._store,
            half_life_days=half_life_days,
            embedder=embedder,
        )

    # ── 写入 ───────────────────────────────────────────────────────────────

    def ingest(
        self,
        text: str,
        *,
        focus: str = "",
        emotion: str = "",
        valence: str = "neutral",
        interactor_id: str = "",
        tags: list[str] | None = None,
        meta: dict | None = None,
        days_ago: float | None = None,
    ) -> str:
        """追加一条记忆到栈顶，返回 unit_id。``days_ago`` 回填时间戳（评测用）。"""
        from datetime import timedelta

        from agent.soul.memory.domain import MemoryTier, Valence
        from agent.soul.memory.graph.base_node import node_now

        body = str(text or "").strip()
        if not body:
            raise ValueError("stack ingest 需要非空 text")
        unit = StackMemoryUnit(
            focus=(focus or body[:24]).strip(),
            content=body,
            tags=[str(t).strip() for t in (tags or []) if str(t).strip()],
            emotion=(emotion or "").strip(),
            emotion_intensity=0.0,
            valence=Valence(str(valence)),
            tier=MemoryTier.short_term,
            interactor_id=(interactor_id or "").strip(),
        )
        if meta:
            unit.meta.update(meta)
        if days_ago is not None and days_ago > 0:
            when = node_now() - timedelta(days=float(days_ago))
            unit.created_at = when
            unit.last_accessed = when
        self._store.push(unit)
        return unit.id

    def push(self, unit: StackMemoryUnit) -> StackMemoryUnit:
        return self._store.push(unit)

    # ── 检索协议（MemoryBasePort）─────────────────────────────────────────

    def recall(
        self,
        query: str,
        top_k: int = 5,
        emotional_context: str = "",
    ) -> MemoryBlock:
        _ = emotional_context
        # 记忆注入入口：无相关命中即返回空块，不用 recent 兜底注入噪声
        scored = self._engine.hybrid(query=query, top_k=top_k, fallback_recent=False)
        unit_ids = [s.unit.id for s in scored]
        if unit_ids:
            self._engine.record_recall(unit_ids)
        entries = [s.render_line() for s in scored]
        return MemoryBlock(label="旁路记忆", entries=entries)

    def search(self, mode: str, **kwargs) -> list[dict]:
        scored = self._engine.search(mode, **kwargs)
        return [self._scored_to_dict(s) for s in scored]

    # ── 旁路运维面 ────────────────────────────────────────────────────────

    @property
    def engine(self) -> StackRetrievalEngine:
        return self._engine

    @property
    def store(self) -> StackMemoryStore:
        return self._store

    def peek(self, top_n: int = 10) -> list[StackMemoryUnit]:
        return self._store.items(limit=top_n)

    def __len__(self) -> int:
        return len(self._store)

    def clear(self) -> int:
        return self._store.clear()

    @staticmethod
    def _scored_to_dict(scored: ScoredUnit) -> dict:
        d = scored.unit.to_dict()
        d["relevance"] = scored.relevance
        d["activation"] = scored.activation
        d["final_score"] = scored.final_score
        d["source"] = scored.source
        return d
