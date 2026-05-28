from __future__ import annotations

from agent.soul.memory.domain import ActivatedNode, MemoryNetwork
from agent.soul.memory.graph.traversal import GraphTraversal, TraversalHit


def spread_activation(
    seeds: dict[str, float],
    traversal: GraphTraversal,
    *,
    threshold: float,
    max_hops: int,
    hop_decay: float,
    network_for: dict[str, MemoryNetwork] | None = None,
) -> list[ActivatedNode]:
    hits: list[TraversalHit] = traversal.bfs(
        seeds,
        max_hops=max_hops,
        hop_decay=hop_decay,
        threshold=threshold,
    )
    out: list[ActivatedNode] = []
    for hit in hits:
        network = MemoryNetwork.event
        if network_for and hit.node_id in network_for:
            network = network_for[hit.node_id]
        out.append(
            ActivatedNode(
                unit_id=hit.node_id,
                network=network,
                score=hit.score,
                hop=hit.hop,
            )
        )
    return out
