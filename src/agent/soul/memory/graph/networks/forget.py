from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.domain import MemoryNetwork

if TYPE_CHECKING:
    from agent.soul.memory.ports import GraphNodeStore, VectorIndexPort


class NetworkForgetEngine:
    """记忆网络遗忘：低激活节点归档，并同步清理向量索引�?""

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
