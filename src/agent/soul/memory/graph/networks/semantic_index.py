from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.soul.memory.domain import MemoryNetwork
from agent.soul.memory.graph.base_node import BaseNode
from agent.soul.memory.embed_text import cosine_similarity

if TYPE_CHECKING:
    from infra.memory import MemoryInfraService


@dataclass(frozen=True)
class IngestedSemanticVector:
    node_id: str
    network: MemoryNetwork
    text: str
    vector: list[float]


class SemanticVectorIndex:
    """Record passage embeddings on ingest for emergence retrieval."""

    def __init__(self, infra: MemoryInfraService | None) -> None:
        self._infra = infra
        self._ingested: dict[str, IngestedSemanticVector] = {}

    @property
    def enabled(self) -> bool:
        return self._infra is not None and self._infra.enabled

    def rehydrate(self, node: BaseNode) -> None:
        text = (getattr(node, "embed_text_cache", "") or node.embed_text()).strip()
        vector = list(getattr(node, "embedding", None) or [])
        if not text or not vector:
            return
        self._ingested[node.id] = IngestedSemanticVector(
            node_id=node.id,
            network=node.network,
            text=text,
            vector=vector,
        )
        if self._infra is not None and self._infra.vectors is not None:
            self._infra.vectors.upsert(node.id, vector)

    def record(self, node: BaseNode) -> None:
        text = node.embed_text().strip()
        if not text:
            return
        vector = self._embed_passage(text)
        if not vector:
            return
        self._ingested[node.id] = IngestedSemanticVector(
            node_id=node.id,
            network=node.network,
            text=text,
            vector=vector,
        )
        if self._infra is not None and self._infra.vectors is not None:
            self._infra.vectors.upsert(node.id, vector)

    def upsert(self, node_id: str, text: str, *, network: MemoryNetwork) -> None:
        text = text.strip()
        if not text:
            return
        vector = self._embed_passage(text)
        if not vector:
            return
        self._ingested[node_id] = IngestedSemanticVector(
            node_id=node_id,
            network=network,
            text=text,
            vector=vector,
        )
        if self._infra is not None and self._infra.vectors is not None:
            self._infra.vectors.upsert(node_id, vector)

    def search(
        self,
        vector: list[float],
        top_k: int,
        *,
        network: MemoryNetwork | None = None,
    ) -> list[tuple[str, float]]:
        if not vector:
            return []
        if self._infra is not None and self._infra.vectors is not None:
            hits = self._infra.vectors.search(vector, top_k=top_k * 3 if network else top_k)
            if network is None:
                return hits[:top_k]
            filtered = [
                (uid, score)
                for uid, score in hits
                if uid in self._ingested and self._ingested[uid].network == network
            ]
            return filtered[:top_k]
        pool = list(self._ingested.values())
        if network is not None:
            pool = [entry for entry in pool if entry.network == network]
        scored = [
            (entry.node_id, cosine_similarity(vector, entry.vector))
            for entry in pool
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def remove(self, node_id: str) -> None:
        self._ingested.pop(node_id, None)
        if self._infra is not None:
            self._infra.remove_unit(node_id)

    def embed_query(self, text: str) -> list[float]:
        if self._infra is None or self._infra.embedding is None:
            return []
        return self._infra.embedding.embed_query(text)

    def embed_passage(self, text: str) -> list[float]:
        return self._embed_passage(text)

    def get(self, node_id: str) -> IngestedSemanticVector | None:
        return self._ingested.get(node_id)

    def iter_entries(self) -> list[IngestedSemanticVector]:
        return list(self._ingested.values())

    def search_subset(
        self,
        vector: list[float],
        node_ids: list[str],
        top_k: int,
        *,
        network: MemoryNetwork | None = None,
    ) -> list[tuple[str, float]]:
        if not vector or not node_ids:
            return []
        pool = [
            self._ingested[nid]
            for nid in node_ids
            if nid in self._ingested
        ]
        if network is not None:
            pool = [entry for entry in pool if entry.network == network]
        scored = [
            (entry.node_id, cosine_similarity(vector, entry.vector))
            for entry in pool
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def _embed_passage(self, text: str) -> list[float]:
        if self._infra is None or self._infra.embedding is None:
            return []
        return self._infra.embedding.embed_passage(text)
