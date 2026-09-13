"""ClusterIndex 聚类索引单元测试（真实导入链）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[4]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.memory.domain import MemoryNetwork
from agent.soul.memory.graph.cluster import ClusterIndex
from agent.soul.memory.graph.networks.semantic_index import IngestedSemanticVector


def test_cluster_rebuild_and_cache_roundtrip():
    entries = [
        IngestedSemanticVector("a", MemoryNetwork.event, "a", [1.0, 0.0]),
        IngestedSemanticVector("b", MemoryNetwork.event, "b", [0.99, 0.01]),
        IngestedSemanticVector("c", MemoryNetwork.event, "c", [0.0, 1.0]),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "clusters.json")
        index = ClusterIndex(similarity_threshold=0.9, min_cluster_size=2, cache_path=path)
        index.rebuild(entries)
        assert index.ready
        cores = index.nearest_cores([1.0, 0.0], network=MemoryNetwork.event, top_k=2)
        assert cores
        members = index.member_ids_near_cores([1.0, 0.0], networks=(MemoryNetwork.event,), top_k=1)
        assert "a" in members or "b" in members

        index2 = ClusterIndex(cache_path=path)
        assert index2.try_load_cache()
        assert index2.ready
        members2 = index2.member_ids_for_cores([index2._clusters[0].core_id])
        assert members2
