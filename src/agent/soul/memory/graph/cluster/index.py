from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Callable

from agent.soul.memory.domain import MemoryNetwork
from agent.soul.memory.embed_text import cosine_similarity
from agent.soul.memory.graph.networks.semantic_index import IngestedSemanticVector


@dataclass(frozen=True)
class MemoryCluster:
    cluster_id: str
    core_id: str
    member_ids: tuple[str, ...]
    centroid: tuple[float, ...]
    network: MemoryNetwork


class ClusterIndex:
    """对注入向量做聚类，检索时先命中聚类核心再局部扫描成员。"""

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.72,
        min_cluster_size: int = 2,
        core_probe_top_k: int = 4,
        cache_path: str = "",
        enqueue: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._similarity_threshold = similarity_threshold
        self._min_cluster_size = min_cluster_size
        self._core_probe_top_k = core_probe_top_k
        self._cache_path = cache_path.strip()
        self._enqueue = enqueue
        self._clusters: list[MemoryCluster] = []
        self._node_to_cluster: dict[str, str] = {}

    @property
    def ready(self) -> bool:
        return bool(self._clusters)

    def bind_enqueue(self, enqueue: Callable[[Callable[[], None]], None]) -> None:
        self._enqueue = enqueue

    def schedule_rebuild(self, entries: list[IngestedSemanticVector]) -> None:
        if self._enqueue is None:
            self.rebuild(entries)
            return
        snapshot = list(entries)
        self._enqueue(lambda: self.rebuild(snapshot))

    def rebuild(self, entries: list[IngestedSemanticVector]) -> None:
        valid = [e for e in entries if e.vector]
        if not valid:
            self._clusters = []
            self._node_to_cluster = {}
            return

        assigned = [False] * len(valid)
        clusters: list[MemoryCluster] = []
        node_to_cluster: dict[str, str] = {}

        for i, seed in enumerate(valid):
            if assigned[i]:
                continue
            member_indices = [i]
            assigned[i] = True
            for j in range(i + 1, len(valid)):
                if assigned[j]:
                    continue
                if cosine_similarity(seed.vector, valid[j].vector) >= self._similarity_threshold:
                    member_indices.append(j)
                    assigned[j] = True

            if len(member_indices) < self._min_cluster_size:
                for idx in member_indices:
                    assigned[idx] = False
                continue

            members = [valid[idx] for idx in member_indices]
            centroid = _centroid([m.vector for m in members])
            sims = [cosine_similarity(centroid, m.vector) for m in members]
            core_local = sims.index(max(sims))
            core = members[core_local]
            cluster_id = str(uuid.uuid4())
            cluster = MemoryCluster(
                cluster_id=cluster_id,
                core_id=core.node_id,
                member_ids=tuple(m.node_id for m in members),
                centroid=tuple(centroid),
                network=core.network,
            )
            clusters.append(cluster)
            for m in members:
                node_to_cluster[m.node_id] = cluster_id

        for i, entry in enumerate(valid):
            if entry.node_id in node_to_cluster:
                continue
            cluster_id = str(uuid.uuid4())
            cluster = MemoryCluster(
                cluster_id=cluster_id,
                core_id=entry.node_id,
                member_ids=(entry.node_id,),
                centroid=tuple(entry.vector),
                network=entry.network,
            )
            clusters.append(cluster)
            node_to_cluster[entry.node_id] = cluster_id

        self._clusters = clusters
        self._node_to_cluster = node_to_cluster
        self._persist_cache()

    def try_load_cache(self) -> bool:
        if not self._cache_path or not os.path.isfile(self._cache_path):
            return False
        with open(self._cache_path, encoding="utf-8") as f:
            payload = json.load(f)
        self.import_state(payload)
        return self.ready

    def export_state(self) -> dict:
        return {
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "core_id": c.core_id,
                    "member_ids": list(c.member_ids),
                    "centroid": list(c.centroid),
                    "network": c.network.value,
                }
                for c in self._clusters
            ]
        }

    def import_state(self, payload: dict) -> None:
        raw = payload.get("clusters") if isinstance(payload, dict) else None
        if not raw:
            self._clusters = []
            self._node_to_cluster = {}
            return
        clusters: list[MemoryCluster] = []
        node_to_cluster: dict[str, str] = {}
        for item in raw:
            cluster_id = str(item["cluster_id"])
            core_id = str(item["core_id"])
            member_ids = tuple(str(mid) for mid in item["member_ids"])
            centroid = tuple(float(v) for v in item["centroid"])
            network = MemoryNetwork(str(item["network"]))
            cluster = MemoryCluster(
                cluster_id=cluster_id,
                core_id=core_id,
                member_ids=member_ids,
                centroid=centroid,
                network=network,
            )
            clusters.append(cluster)
            for mid in member_ids:
                node_to_cluster[mid] = cluster_id
        self._clusters = clusters
        self._node_to_cluster = node_to_cluster

    def _persist_cache(self) -> None:
        if not self._cache_path or not self._clusters:
            return
        directory = os.path.dirname(self._cache_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(self.export_state(), f, ensure_ascii=False)

    def nearest_cores(
        self,
        query_vector: list[float],
        *,
        network: MemoryNetwork | None = None,
        top_k: int | None = None,
    ) -> list[tuple[str, float]]:
        if not query_vector or not self._clusters:
            return []
        k = top_k if top_k is not None else self._core_probe_top_k
        scored: list[tuple[str, float]] = []
        for cluster in self._clusters:
            if network is not None and cluster.network != network:
                continue
            score = cosine_similarity(query_vector, list(cluster.centroid))
            scored.append((cluster.core_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

    def member_ids_for_cores(self, core_ids: list[str]) -> list[str]:
        core_set = set(core_ids)
        out: list[str] = []
        seen: set[str] = set()
        for cluster in self._clusters:
            if cluster.core_id not in core_set:
                continue
            for node_id in cluster.member_ids:
                if node_id in seen:
                    continue
                seen.add(node_id)
                out.append(node_id)
        return out

    def member_ids_near_cores(
        self,
        query_vector: list[float],
        *,
        networks: tuple[MemoryNetwork, ...],
        top_k: int | None = None,
    ) -> list[str]:
        if not query_vector:
            return []
        core_ids: list[str] = []
        for network in networks:
            for core_id, _ in self.nearest_cores(query_vector, network=network, top_k=top_k):
                if core_id not in core_ids:
                    core_ids.append(core_id)
        return self.member_ids_for_cores(core_ids)


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    return [
        sum(v[d] for v in vectors) / len(vectors)
        for d in range(dim)
    ]
