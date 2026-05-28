from __future__ import annotations

from agent.soul.memory.activation.engine import spread_activation
from agent.soul.memory.domain import EdgeType, MemoryEdge, MemoryNetwork
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
        return []

    def delete_by_node(self, node_id: str) -> None:
        pass


def test_spread_activation_respects_threshold():
    edges = [
        MemoryEdge(from_id="seed", to_id="near", edge_type=EdgeType.about, weight=1.0),
        MemoryEdge(from_id="near", to_id="far", edge_type=EdgeType.related_to, weight=1.0),
    ]
    traversal = GraphTraversal(_FakeEdgeStore(edges))
    activated = spread_activation(
        {"seed": 0.8},
        traversal,
        threshold=0.21,
        max_hops=2,
        hop_decay=0.5,
        network_for={"seed": MemoryNetwork.social, "near": MemoryNetwork.social, "far": MemoryNetwork.social},
    )
    ids = {a.unit_id for a in activated}
    assert "seed" in ids
    assert "near" in ids
    assert "far" not in ids
