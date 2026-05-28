from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from agent.soul.memory.domain import EdgeType
from agent.soul.memory.ports import GraphEdgeStore


@dataclass
class TraversalHit:
    node_id: str
    score: float
    hop: int


class GraphTraversal:
    def __init__(self, edges: GraphEdgeStore) -> None:
        self._edges = edges

    def bfs(
        self,
        start_scores: dict[str, float],
        *,
        max_hops: int,
        hop_decay: float,
        threshold: float,
    ) -> list[TraversalHit]:
        best: dict[str, TraversalHit] = {}
        queue: deque[tuple[str, float, int]] = deque()

        for node_id, score in start_scores.items():
            if score < threshold:
                continue
            queue.append((node_id, score, 0))
            best[node_id] = TraversalHit(node_id=node_id, score=score, hop=0)

        while queue:
            node_id, score, hop = queue.popleft()
            if hop >= max_hops:
                continue
            for edge in self._edges.out_edges(node_id):
                next_score = score * edge.weight * hop_decay
                if next_score < threshold:
                    continue
                next_hop = hop + 1
                prev = best.get(edge.to_id)
                if prev is not None and prev.score >= next_score:
                    continue
                hit = TraversalHit(node_id=edge.to_id, score=next_score, hop=next_hop)
                best[edge.to_id] = hit
                queue.append((edge.to_id, next_score, next_hop))

        return sorted(best.values(), key=lambda h: h.score, reverse=True)

    def link_source_of(self, from_id: str, to_id: str, *, weight: float = 1.0) -> None:
        from agent.soul.memory.domain import MemoryEdge

        self._edges.put(
            MemoryEdge(from_id=from_id, to_id=to_id, edge_type=EdgeType.source_of, weight=weight)
        )

    def link_weaves(self, narrative_id: str, source_id: str, *, weight: float = 0.8) -> None:
        from agent.soul.memory.domain import MemoryEdge

        self._edges.put(
            MemoryEdge(
                from_id=narrative_id,
                to_id=source_id,
                edge_type=EdgeType.weaves,
                weight=weight,
            )
        )

    def link_about(self, core_id: str, neighborhood_id: str, *, weight: float = 1.0) -> None:
        from agent.soul.memory.domain import MemoryEdge

        self._edges.put(
            MemoryEdge(
                from_id=core_id,
                to_id=neighborhood_id,
                edge_type=EdgeType.about,
                weight=weight,
            )
        )

    def link_related_to(self, from_id: str, to_id: str, *, weight: float = 0.9) -> None:
        from agent.soul.memory.domain import MemoryEdge

        self._edges.put(
            MemoryEdge(
                from_id=from_id,
                to_id=to_id,
                edge_type=EdgeType.related_to,
                weight=weight,
            )
        )

    def link_involves(self, from_id: str, to_id: str, *, weight: float = 0.85) -> None:
        from agent.soul.memory.domain import MemoryEdge

        self._edges.put(
            MemoryEdge(
                from_id=from_id,
                to_id=to_id,
                edge_type=EdgeType.involves,
                weight=weight,
            )
        )
