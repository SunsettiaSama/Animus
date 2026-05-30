from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.memory.graph.node_store import GraphNodeStore


def record_recall_batch(nodes: GraphNodeStore, unit_ids: list[str]) -> None:
    for uid in unit_ids:
        nodes.on_recall(uid)
