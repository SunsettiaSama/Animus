from __future__ import annotations

from typing import Callable

from agent.soul.memory.activation.engine import spread_activation
from agent.soul.memory.activation.snapshot_store import ActivationSnapshotStore, cue_hash
from agent.soul.memory.domain import ActivationCue, ActivationSnapshot, MemoryNetwork
from agent.soul.memory.graph.seeds import SeedResolver
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.ports import GraphEdgeStore, GraphNodeStore, VectorIndexPort


class ActivationService:
    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        vectors: VectorIndexPort | None,
        *,
        threshold: float = 0.12,
        max_hops: int = 3,
        hop_decay: float = 0.72,
        seed_top_k: int = 8,
        keyword_weight: float = 0.55,
        enqueue: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._nodes = nodes
        self._traversal = GraphTraversal(edges)
        self._seeds = SeedResolver(
            nodes,
            vectors,
            keyword_weight=keyword_weight,
            seed_top_k=seed_top_k,
        )
        self._vectors = vectors
        self._threshold = threshold
        self._max_hops = max_hops
        self._hop_decay = hop_decay
        self._snapshots = ActivationSnapshotStore()
        self._enqueue = enqueue

    def activate_async(self, cue: ActivationCue) -> None:
        if self._enqueue is None:
            self._run(cue)
            return
        self._enqueue(lambda: self._run(cue))

    def get_snapshot(self, session_id: str) -> ActivationSnapshot | None:
        return self._snapshots.get(session_id)

    def activate_sync(self, cue: ActivationCue) -> ActivationSnapshot:
        return self._run(cue)

    def _run(self, cue: ActivationCue) -> ActivationSnapshot:
        text = " ".join(part for part in (cue.user_text, cue.agent_text) if part.strip())
        seed_scores = self._seeds.resolve(
            text,
            networks=cue.networks,
            interactor_id=cue.interactor_id,
        )
        network_for: dict[str, MemoryNetwork] = {}
        for node_id in seed_scores:
            node = self._nodes.get(node_id)
            if node is not None:
                network_for[node_id] = node.network
        activated = spread_activation(
            seed_scores,
            self._traversal,
            threshold=self._threshold,
            max_hops=self._max_hops,
            hop_decay=self._hop_decay,
            network_for=network_for,
        )
        snapshot = ActivationSnapshot(
            session_id=cue.session_id,
            interactor_id=cue.interactor_id,
            nodes=activated,
            cue_hash=cue_hash(cue.session_id, cue.user_text, cue.agent_text, cue.interactor_id),
        )
        self._snapshots.put(snapshot)
        return snapshot
