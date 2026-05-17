from __future__ import annotations

from config.agent.memory.memory_config import LongTermMemoryConfig
from ...memory.long_term.retrieve.dispatcher import Retriever
from ...memory.long_term.store import LongTermStore, MemoryEntry


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


class LongTermMemory:
    def __init__(self, store: LongTermStore, cfg: LongTermMemoryConfig) -> None:
        self._store = store
        self._cfg = cfg
        self._retriever = Retriever(store, cfg.retrieve)

    def add(self, text: str, **meta) -> MemoryEntry:
        return self._store.add(text, **meta)

    def recall(self, query: str) -> str:
        """简单召回（向后兼容），不做模式判断。"""
        return self._store.recall(query)

    def recall_timeline(self, n: int = 5) -> str:
        """Return the n most recent memories in chronological order with timestamps."""
        pairs = self._store.recall_timeline(n)
        if not pairs:
            return ""
        parts = [
            f"[{created_at[:16].replace('T', ' ')} UTC]\n{text}"
            for created_at, text in pairs
        ]
        return "\n\n".join(parts)

    def smart_recall(
        self,
        query: str,
        is_session_start: bool = False,
        short_term_context: str = "",
        medium_term_context: str = "",
    ) -> str:
        """智能召回：根据上下文自动选择 LIGHT/HEAVY/SUPPLEMENT/PROFILE 模式。"""
        result = self._retriever.auto_retrieve(
            query=query,
            is_session_start=is_session_start,
            short_term_context=short_term_context,
            medium_term_context=medium_term_context,
        )
        return _trunc(result.combined, self._cfg.max_recall_chars)

    def save(self) -> None:
        self._store.save()

    @property
    def store(self) -> LongTermStore:
        return self._store
