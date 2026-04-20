from __future__ import annotations

from react.memory.long_term.store import LongTermStore, MemoryEntry


class LongTermMemory:
    def __init__(self, store: LongTermStore):
        self._store = store

    def add(self, text: str, **meta) -> MemoryEntry:
        return self._store.add(text, **meta)

    def recall(self, query: str) -> str:
        return self._store.recall(query)

    def save(self) -> None:
        self._store.save()

    @property
    def store(self) -> LongTermStore:
        return self._store
