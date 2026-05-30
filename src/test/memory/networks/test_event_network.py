from __future__ import annotations

import json

from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.memory.domain import EdgeType, FactualMemory, MemoryEdge, MemoryNetwork
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.graph.node.create.archive import ExperienceArchiver
from agent.soul.memory.graph.networks.writer import NarrativeWriter
from agent.soul.memory.graph.networks.event.network import EventMemoryNetwork


class _Cfg:
    forget_threshold = 0.05
    half_life_days = 30.0
    narrative_threshold = 0.9
    recent_half_life_days = 3.0


class _MemStore:
    def __init__(self) -> None:
        self._nodes: dict[str, object] = {}

    def put(self, node) -> None:
        self._nodes[node.id] = node

    def get(self, node_id: str):
        return self._nodes.get(node_id)

    def get_many(self, node_ids: list[str]):
        return [self._nodes[i] for i in node_ids if i in self._nodes]

    def list_recent(self, memory_type=None, valence=None, network=None, limit: int = 50):
        out = list(self._nodes.values())
        if network is not None:
            out = [n for n in out if n.network == network]
        return out[:limit]

    def list_by_network(self, network, *, limit: int = 50):
        return self.list_recent(network=network, limit=limit)

    def get_by_life_event_id(self, life_event_id: str):
        for node in self._nodes.values():
            meta = getattr(node, "meta", {}) or {}
            if meta.get("life_event_id") == life_event_id:
                return node
        return None

    def archive(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)

    def on_recall(self, node_id: str) -> None:
        pass

    def add_rehearsal(self, node_id: str) -> None:
        pass

    def add_narrative_ref(self, node_id: str) -> None:
        pass

    def forget_scan(self, **kwargs):
        return []


class _EdgeStore:
    def __init__(self) -> None:
        self.edges: list[MemoryEdge] = []

    def put(self, edge: MemoryEdge) -> None:
        self.edges.append(edge)

    def out_edges(self, node_id: str, edge_type=None):
        return [e for e in self.edges if e.from_id == node_id]

    def in_edges(self, node_id: str, edge_type=None):
        return []

    def delete_by_node(self, node_id: str) -> None:
        self.edges = [e for e in self.edges if e.from_id != node_id and e.to_id != node_id]


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def generate_messages(self, messages) -> str:
        return json.dumps(self._payload, ensure_ascii=False)


def test_event_ingest_grows_network_from_parent():
    nodes = _MemStore()
    edges = _EdgeStore()
    parent = FactualMemory(focus="整理笔记", fact="昨天整理笔记", perception="我整理了笔记")
    nodes.put(parent)

    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            perception="午后阳光落在书桌上",
            narration="独自整理笔记",
        ),
        action=ExperienceAction(kind=ExperienceActionKind.reasoning, content="回顾今天"),
        feeling=ExperienceFeeling(salience=0.55, emotion_label="平静"),
        source="narrative",
    )
    llm = _FakeLLM(
        {
            "focus": "午后整理",
            "subjective_statement": "我在午后阳光里继续整理笔记，心里很安静",
            "parent_node_id": parent.id,
            "parent_reason": "同一主题的延续",
            "emotion": "平静",
            "emotion_intensity": 0.55,
            "valence": "neutral",
            "base_activation": 0.6,
        }
    )
    archiver = ExperienceArchiver(llm, nodes)
    event = EventMemoryNetwork(
        nodes,
        edges,
        QueryEngine(nodes),
        NarrativeWriter(llm, nodes),
        _Cfg(),
        archiver,
    )
    mem = event.ingest_event_experience(unit)
    assert isinstance(mem, FactualMemory)
    assert mem.perception.startswith("我在午后")
    assert any(
        e.edge_type == EdgeType.related_to and e.from_id == parent.id and e.to_id == mem.id
        for e in edges.edges
    )


def test_router_routes_event_to_event_network():
    nodes = _MemStore()
    edges = _EdgeStore()
    llm = _FakeLLM(
        {
            "focus": "午后整理",
            "subjective_statement": "我在午后整理笔记",
            "parent_node_id": "none",
            "parent_reason": "",
            "emotion": "平静",
            "emotion_intensity": 0.5,
            "valence": "neutral",
            "base_activation": 0.5,
        }
    )
    archiver = ExperienceArchiver(llm, nodes)
    event = EventMemoryNetwork(
        nodes,
        edges,
        QueryEngine(nodes),
        NarrativeWriter(llm, nodes),
        _Cfg(),
        archiver,
    )

    unit = ExperienceUnit.make(
        situation=ExperienceSituation(perception="地标", narration="散步"),
        action=ExperienceAction(kind=ExperienceActionKind.attending, content="路过"),
        feeling=ExperienceFeeling(salience=0.4),
        source="surprise",
    )
    node = event.ingest_event_experience(unit)
    assert isinstance(node, FactualMemory)
    assert node.network == MemoryNetwork.event
