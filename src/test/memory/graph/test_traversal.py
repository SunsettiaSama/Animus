from __future__ import annotations

from agent.soul.memory.domain import EdgeType, MemoryEdge
from agent.soul.memory.graph.traversal import GraphTraversal


class _FakeEdgeStore:
    def __init__(self, edges: list[MemoryEdge]) -> None:
        self._edges = edges

    def put(self, edge: MemoryEdge) -> None:
        self._edges.append(edge)

    def out_edges(self, node_id: str, edge_type: EdgeType | None = None):
        out = [e for e in self._edges if e.from_id == node_id]
        if edge_type is not None:
            out = [e for e in out if e.edge_type == edge_type]
        return out

    def in_edges(self, node_id: str, edge_type: EdgeType | None = None):
        inn = [e for e in self._edges if e.to_id == node_id]
        if edge_type is not None:
            inn = [e for e in inn if e.edge_type == edge_type]
        return inn

    def delete_edge(self, edge_id: str) -> None:
        self._edges = [e for e in self._edges if e.id != edge_id]

    def delete_by_node(self, node_id: str) -> None:
        self._edges = [e for e in self._edges if e.from_id != node_id and e.to_id != node_id]


def test_bfs_spreads_with_decay():
    edges = [
        MemoryEdge(from_id="a", to_id="b", edge_type=EdgeType.related_to, weight=1.0),
        MemoryEdge(from_id="b", to_id="c", edge_type=EdgeType.related_to, weight=1.0),
    ]
    traversal = GraphTraversal(_FakeEdgeStore(edges))
    hits = traversal.bfs({"a": 1.0}, max_hops=2, hop_decay=0.5, threshold=0.1)
    scores = {h.node_id: h.score for h in hits}
    assert scores["a"] == 1.0
    assert scores["b"] == 0.5
    assert scores["c"] == 0.25
