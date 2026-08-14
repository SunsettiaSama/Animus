"""memory_distill chain — degraded periodic mid/long-term memory compression."""
from __future__ import annotations

from typing import Any

from worker.state.chain import StateDerivationChain
from worker.state.memory_distill.bundle import PortraitSourceBundle
from worker.state.memory_distill.source import MemoryPort, MediumPort, gather_portrait_source
from worker.state.memory_distill.writer import MemoryPortraitWriter
from worker.state.schema import MEMORY_PORTRAIT_SLOT, MemoryPortraitState, StateSlot
from worker.state.store import AgentStateStore

# First (and currently only) state submodule — also the fallback derivation path.
CHAIN_ID = "memory_distill"
CHAIN_ROLE = "fallback"


class MemoryDistillChain(StateDerivationChain[PortraitSourceBundle, MemoryPortraitState]):
    """Degraded state chain: mid/long-term memory → memory_portrait slot.

    Used as the default refresh path until richer state chains exist.
    """

    slot_type = MEMORY_PORTRAIT_SLOT
    chain_id = CHAIN_ID
    chain_role = CHAIN_ROLE

    def __init__(
        self,
        store: AgentStateStore,
        *,
        llm: Any,
        memory: MemoryPort | None = None,
        medium: MediumPort | None = None,
        persona_revision: str = "",
        stable_anchor: str = "",
        hybrid_query: str = "",
        worker_unit_lines: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(store)
        self._memory = memory
        self._medium = medium
        self._persona_revision = persona_revision
        self._stable_anchor = stable_anchor
        self._hybrid_query = hybrid_query
        self._worker_unit_lines = tuple(worker_unit_lines or ())
        self._writer = MemoryPortraitWriter(llm)

    def gather(self) -> PortraitSourceBundle:
        return gather_portrait_source(
            memory=self._memory,
            medium=self._medium,
            persona_revision=self._persona_revision,
            stable_anchor=self._stable_anchor,
            hybrid_query=self._hybrid_query,
            worker_unit_lines=self._worker_unit_lines,
        )
    def source_revision(self, source: PortraitSourceBundle) -> str:
        return source.source_revision

    def is_source_empty(self, source: PortraitSourceBundle) -> bool:
        return source.is_empty

    def derive(
        self,
        source: PortraitSourceBundle,
        *,
        current: StateSlot | None,
    ) -> MemoryPortraitState:
        _ = current
        return self._writer.distill(source)
