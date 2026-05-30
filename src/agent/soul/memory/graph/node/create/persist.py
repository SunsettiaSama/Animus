from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from agent.soul.memory.graph.base_node import BaseNode

if TYPE_CHECKING:
    from agent.soul.memory.graph.node_store import GraphNodeStore
    from agent.soul.memory.ports import VectorIndexPort


class NodePersister:
    """单节点写入：MySQL put + 可选向量索引 + 写后回调。"""

    def __init__(
        self,
        nodes: GraphNodeStore,
        *,
        vectors: VectorIndexPort | None = None,
        on_written: Callable[[BaseNode], None] | None = None,
    ) -> None:
        self._nodes = nodes
        self._vectors = vectors
        self._on_written = on_written

    def write(self, node: BaseNode, *, embed: bool = True) -> BaseNode:
        if embed:
            embed_text = node.embed_text().strip()
            node.embed_text_cache = embed_text
            if self._vectors is not None and embed_text:
                vector = self._vectors.embed_passage(embed_text)
                node.embedding = vector
                if vector:
                    self._vectors.upsert(node.id, embed_text, network=node.network)
        self._nodes.put(node)
        self._notify(node)
        return node

    def put_only(self, node: BaseNode) -> BaseNode:
        self._nodes.put(node)
        return node

    def notify(self, node: BaseNode) -> None:
        self._notify(node)

    def _notify(self, node: BaseNode) -> None:
        if self._on_written is not None:
            self._on_written(node)
