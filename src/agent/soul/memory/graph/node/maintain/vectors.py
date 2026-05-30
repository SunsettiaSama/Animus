from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.memory.graph.base_node import BaseNode
    from agent.soul.memory.ports import VectorIndexPort


def record_node(vectors: VectorIndexPort, node: BaseNode) -> None:
    vectors.record(node)


def remove_node(vectors: VectorIndexPort, node_id: str) -> None:
    vectors.remove(node_id)
