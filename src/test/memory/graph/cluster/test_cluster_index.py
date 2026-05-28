from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[4]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_agent = sys.modules.setdefault("agent", types.ModuleType("agent"))
_agent.__path__ = [str(SRC / "agent")]
_soul = types.ModuleType("agent.soul")
_soul.__path__ = [str(SRC / "agent" / "soul")]
_soul.__package__ = "agent.soul"
sys.modules["agent.soul"] = _soul

_memory = types.ModuleType("agent.soul.memory")
_memory.__path__ = [str(SRC / "agent" / "soul" / "memory")]
_memory.__package__ = "agent.soul.memory"
sys.modules["agent.soul.memory"] = _memory

_embed = types.ModuleType("agent.soul.memory.embed_text")
_embed.cosine_similarity = lambda a, b: sum(x * y for x, y in zip(a, b))
sys.modules["agent.soul.memory.embed_text"] = _embed

_enums_spec = importlib.util.spec_from_file_location(
    "agent.soul.memory.domain.enums",
    SRC / "agent/soul/memory/domain/enums.py",
)
_enums_mod = importlib.util.module_from_spec(_enums_spec)
sys.modules["agent.soul.memory.domain.enums"] = _enums_mod
_enums_spec.loader.exec_module(_enums_mod)

_domain = types.ModuleType("agent.soul.memory.domain")
_domain.MemoryNetwork = _enums_mod.MemoryNetwork
sys.modules["agent.soul.memory.domain"] = _domain

_sem_mod = types.ModuleType("agent.soul.memory.graph.networks.semantic_index")


@dataclass(frozen=True)
class IngestedSemanticVector:
    node_id: str
    network: object
    text: str
    vector: list[float]


_sem_mod.IngestedSemanticVector = IngestedSemanticVector
sys.modules["agent.soul.memory.graph.networks.semantic_index"] = _sem_mod

_cluster_pkg = types.ModuleType("agent.soul.memory.graph.cluster")
_cluster_pkg.__path__ = [str(SRC / "agent" / "soul" / "memory" / "graph" / "cluster")]
sys.modules["agent.soul.memory.graph.cluster"] = _cluster_pkg

_cluster_spec = importlib.util.spec_from_file_location(
    "agent.soul.memory.graph.cluster.index",
    SRC / "agent/soul/memory/graph/cluster/index.py",
)
_cluster_mod = importlib.util.module_from_spec(_cluster_spec)
sys.modules["agent.soul.memory.graph.cluster.index"] = _cluster_mod
_cluster_spec.loader.exec_module(_cluster_mod)

ClusterIndex = _cluster_mod.ClusterIndex
MemoryNetwork = _enums_mod.MemoryNetwork


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
