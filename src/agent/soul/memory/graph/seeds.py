from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.domain import GraphNode, MemoryNetwork
from agent.soul.memory.graph.keywords import extract_keywords
from agent.soul.memory.ports import GraphNodeStore, VectorIndexPort

if TYPE_CHECKING:
    from agent.soul.memory.graph.cluster import ClusterIndex
    from agent.soul.memory.graph.networks.semantic_index import SemanticVectorIndex


class SeedResolver:
    def __init__(
        self,
        nodes: GraphNodeStore,
        vectors: VectorIndexPort | None,
        *,
        keyword_weight: float = 0.55,
        seed_top_k: int = 8,
        cluster_index: ClusterIndex | None = None,
        cluster_core_top_k: int = 4,
    ) -> None:
        self._nodes = nodes
        self._vectors = vectors
        self._keyword_weight = keyword_weight
        self._seed_top_k = seed_top_k
        self._cluster_index = cluster_index
        self._cluster_core_top_k = cluster_core_top_k

    def resolve(
        self,
        text: str,
        *,
        networks: tuple[MemoryNetwork, ...],
        interactor_id: str = "",
    ) -> dict[str, float]:
        seeds: dict[str, float] = {}
        combined = text.strip()
        if not combined:
            return seeds

        if self._vectors is not None:
            vector = self._vectors.embed_query(combined)
            if vector:
                for network in networks:
                    hits = self._resolve_semantic_hits(vector, network)
                    for node_id, sim in hits:
                        seeds[node_id] = max(seeds.get(node_id, 0.0), sim)

        keywords = extract_keywords(combined)
        if keywords:
            for network in networks:
                candidates = self._nodes.list_by_network(network, limit=max(80, self._seed_top_k * 6))
                for node in candidates:
                    if interactor_id and node.interactor_id and node.interactor_id != interactor_id:
                        if network == MemoryNetwork.social:
                            continue
                    hay = self._node_haystack(node).lower()
                    if any(kw in hay for kw in keywords):
                        seeds[node.id] = max(
                            seeds.get(node.id, 0.0),
                            self._keyword_weight,
                        )

        return seeds

    def _resolve_semantic_hits(
        self,
        vector: list[float],
        network: MemoryNetwork,
    ) -> list[tuple[str, float]]:
        index = self._cluster_index
        vectors = self._vectors
        if (
            index is not None
            and index.ready
            and vectors is not None
            and hasattr(vectors, "search_subset")
            and hasattr(vectors, "iter_entries")
        ):
            member_ids = index.member_ids_near_cores(
                vector,
                networks=(network,),
                top_k=self._cluster_core_top_k,
            )
            if member_ids:
                return vectors.search_subset(
                    vector,
                    member_ids,
                    self._seed_top_k,
                    network=network,
                )
        if vectors is None:
            return []
        return vectors.search(vector, self._seed_top_k, network=network)

    @staticmethod
    def _node_haystack(node: GraphNode) -> str:
        parts = [node.focus, node.emotion]
        for attr in ("fact", "perception", "reconstructed_fact", "narrative", "core_traits", "content", "label"):
            val = getattr(node, attr, "")
            if val:
                parts.append(str(val))
        return " ".join(parts)
