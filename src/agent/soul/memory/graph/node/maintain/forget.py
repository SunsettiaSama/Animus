from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.domain import MemoryNetwork

if TYPE_CHECKING:
    from agent.soul.memory.graph.node_store import GraphNodeStore
    from agent.soul.memory.ports import VectorIndexPort


class NodeForgetEngine:
    """节点遗忘扫描：低激活 soft-delete + 向量清理。"""

    def forget_scan(
        self,
        nodes: GraphNodeStore,
        *,
        threshold: float,
        half_life_days: float,
        dry_run: bool,
        network: MemoryNetwork | None = None,
        vectors: VectorIndexPort | None = None,
    ) -> list[str]:
        archived = nodes.forget_scan(
            threshold=threshold,
            half_life_days=half_life_days,
            dry_run=dry_run,
            network=network,
        )
        if not dry_run and vectors is not None:
            for uid in archived:
                vectors.remove(uid)
        return archived
