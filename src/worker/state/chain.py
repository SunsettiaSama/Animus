"""StateDerivationChain — unified read → gather → derive → commit paradigm."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from worker.state.schema import ChainResult, StateSlot
from worker.state.store import AgentStateStore

S = TypeVar("S")
T = TypeVar("T", bound=StateSlot)


class StateDerivationChain(ABC, Generic[S, T]):
    """Template for all Agent State derivation pipelines.

    Contract:
      1. read current slot
      2. gather source materials (+ source_revision)
      3. if source empty or revision unchanged → return current (no LLM / no write)
      4. derive candidate slot
      5. commit into store
    """

    slot_type: str

    def __init__(self, store: AgentStateStore) -> None:
        self._store = store

    def run(self, *, force: bool = False) -> ChainResult:
        current = self._store.read(self.slot_type)
        source = self.gather()
        revision = self.source_revision(source)

        if self.is_source_empty(source):
            return ChainResult(slot=current, refreshed=False, reason="empty_source")

        if (
            not force
            and current is not None
            and current.is_current(revision)
        ):
            return ChainResult(slot=current, refreshed=False, reason="cache_hit")

        candidate = self.derive(source, current=current)
        self._store.commit(candidate)
        return ChainResult(slot=candidate, refreshed=True, reason="derived")

    @abstractmethod
    def gather(self) -> S:
        raise NotImplementedError

    @abstractmethod
    def source_revision(self, source: S) -> str:
        raise NotImplementedError

    @abstractmethod
    def is_source_empty(self, source: S) -> bool:
        raise NotImplementedError

    @abstractmethod
    def derive(self, source: S, *, current: StateSlot | None) -> T:
        raise NotImplementedError
