from __future__ import annotations

from react.memory.long_term.store import LongTermStore


class LongTermMemory:
    def __init__(self, store: LongTermStore):
        self._store = store

    def recall(self, query: str) -> str:
        return self._store.recall(query)

    @property
    def store(self) -> LongTermStore:
        return self._store
