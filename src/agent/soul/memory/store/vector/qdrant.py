from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.domain import MemoryNetwork
from agent.soul.memory.ports import VectorIndexPort

if TYPE_CHECKING:
    from infra.memory import MemoryInfraService


class QdrantVectorIndex:
    def __init__(self, infra: MemoryInfraService) -> None:
        self._infra = infra

    @property
    def enabled(self) -> bool:
        return self._infra.enabled

    def upsert(self, node_id: str, text: str, *, network: MemoryNetwork) -> None:
        if not self._infra.enabled:
            return
        self._infra.index_unit(node_id, text)

    def search(
        self,
        vector: list[float],
        top_k: int,
        *,
        network: MemoryNetwork | None = None,
    ) -> list[tuple[str, float]]:
        if not self._infra.enabled or self._infra.vectors is None:
            return []
        hits = self._infra.vectors.search(vector, top_k=top_k)
        if network is None:
            return hits
        return hits

    def remove(self, node_id: str) -> None:
        if self._infra.enabled:
            self._infra.remove_unit(node_id)

    def embed_query(self, text: str) -> list[float]:
        embedder = self._infra.retriever_embedder()
        if embedder is None:
            return []
        return embedder.embed(text)
