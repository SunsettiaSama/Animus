from __future__ import annotations

import importlib.util
import sys
import types
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

_ports = types.ModuleType("agent.soul.memory.ports")
_ports.GraphEdgeStore = object
sys.modules["agent.soul.memory.ports"] = _ports

_graph = types.ModuleType("agent.soul.memory.graph")
_graph.__path__ = [str(SRC / "agent" / "soul" / "memory" / "graph")]
_graph.__package__ = "agent.soul.memory.graph"
sys.modules["agent.soul.memory.graph"] = _graph


def _load(name: str, rel: str):
    path = SRC / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_enums = _load("agent.soul.memory.domain.enums", "agent/soul/memory/domain/enums.py")
_edge = _load("agent.soul.memory.domain.edge", "agent/soul/memory/domain/edge.py")
_activation = _load("agent.soul.memory.domain.activation", "agent/soul/memory/domain/activation.py")

_domain = types.ModuleType("agent.soul.memory.domain")
_domain.EdgeType = _enums.EdgeType
_domain.MemoryNetwork = _enums.MemoryNetwork
_domain.ActivatedNode = _activation.ActivatedNode
sys.modules["agent.soul.memory.domain"] = _domain

_traversal = _load("agent.soul.memory.graph.traversal", "agent/soul/memory/graph/traversal.py")
_engine = _load("agent.soul.memory.emergence.spread.engine", "agent/soul/memory/emergence/spread/engine.py")

EdgeType = _enums.EdgeType
MemoryEdge = _edge.MemoryEdge
MemoryNetwork = _enums.MemoryNetwork
GraphTraversal = _traversal.GraphTraversal
spread_activation = _engine.spread_activation


class _FakeEdgeStore:
    def __init__(self, edges: list[MemoryEdge]) -> None:
        self._edges = edges

    def put(self, edge: MemoryEdge) -> None:
        self._edges.append(edge)

    def out_edges(self, node_id: str, edge_type: EdgeType | None = None):
        out = [e for e in self._edges if e.from_id == node_id]
        if edge_type is not None:
            out = [e for e in out if e.edge_type == edge_type]
        return out

    def in_edges(self, node_id: str, edge_type: EdgeType | None = None):
        return []

    def delete_by_node(self, node_id: str) -> None:
        pass


def test_spread_activation_respects_threshold():
    edges = [
        MemoryEdge(from_id="seed", to_id="near", edge_type=EdgeType.about, weight=1.0),
        MemoryEdge(from_id="near", to_id="far", edge_type=EdgeType.related_to, weight=1.0),
    ]
    traversal = GraphTraversal(_FakeEdgeStore(edges))
    activated = spread_activation(
        {"seed": 0.8},
        traversal,
        threshold=0.21,
        max_hops=2,
        hop_decay=0.5,
        network_for={"seed": MemoryNetwork.social, "near": MemoryNetwork.social, "far": MemoryNetwork.social},
    )
    ids = {a.unit_id for a in activated}
    assert "seed" in ids
    assert "near" in ids
    assert "far" not in ids
