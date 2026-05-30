from __future__ import annotations

import json

from agent.soul.life.experience.domain.anchor_codec import AnchorUnitContext, InteractionDirection, stamp_anchor_context
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.memory.domain import EdgeType, MemoryEdge, SocialCoreNode, SocialNeighborhoodNode, SocialNodeRole
from agent.soul.memory.graph.node.create.archive import ExperienceArchiver
from agent.soul.memory.graph.networks.experience_block import classify_experience, read_experience_block
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.networks.types import ExperienceKind


class _MemStore:
    def __init__(self) -> None:
        self._nodes: dict[str, object] = {}

    def put(self, node) -> None:
        self._nodes[node.id] = node

    def get(self, node_id: str):
        return self._nodes.get(node_id)

    def get_many(self, node_ids: list[str]):
        return [self._nodes[i] for i in node_ids if i in self._nodes]

    def list_by_network(self, network, *, limit: int = 50):
        return [n for n in self._nodes.values() if n.network == network][:limit]

    def list_by_interactor(self, interactor_id: str, role=None, *, limit: int = 50):
        out = []
        for node in self._nodes.values():
            if getattr(node, "interactor_id", "") != interactor_id:
                continue
            if role is not None and getattr(node, "node_role", None) != role:
                continue
            out.append(node)
        return out[:limit]

    def list_recent(self, memory_type=None, valence=None, network=None, limit: int = 50):
        out = list(self._nodes.values())
        if network is not None:
            out = [n for n in out if n.network == network]
        return out[:limit]

    def get_core_for_interactor(self, interactor_id: str):
        nodes = self.list_by_interactor(interactor_id, SocialNodeRole.core, limit=1)
        return nodes[0] if nodes else None

    def get_by_life_event_id(self, life_event_id: str):
        for node in self._nodes.values():
            meta = getattr(node, "meta", {}) or {}
            if meta.get("life_event_id") == life_event_id:
                return node
            if getattr(node, "life_event_id", "") == life_event_id:
                return node
        return None

    def archive(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)

    def on_recall(self, node_id: str) -> None:
        pass

    def add_rehearsal(self, node_id: str) -> None:
        pass

    def forget_scan(self, **kwargs):
        return []


class _EdgeStore:
    def __init__(self) -> None:
        self.edges: list[MemoryEdge] = []

    def put(self, edge: MemoryEdge) -> None:
        self.edges.append(edge)

    def out_edges(self, node_id: str, edge_type: EdgeType | None = None):
        out = [e for e in self.edges if e.from_id == node_id]
        if edge_type is not None:
            out = [e for e in out if e.edge_type == edge_type]
        return out

    def in_edges(self, node_id: str, edge_type: EdgeType | None = None):
        return []

    def delete_by_node(self, node_id: str) -> None:
        self.edges = [e for e in self.edges if e.from_id != node_id and e.to_id != node_id]


class _InteractorStore:
    def get_or_create(self, interactor_id: str, *, display_name: str = ""):
        from agent.soul.memory.domain import InteractorRef

        return InteractorRef(id=interactor_id, display_name=display_name)

    def get(self, interactor_id: str):
        return self.get_or_create(interactor_id)


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def generate_messages(self, messages) -> str:
        return json.dumps(self._payload, ensure_ascii=False)


def _anchor_unit(text: str = "用户：我养了一只猫") -> ExperienceUnit:
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id="s1",
            perception=text,
            narration="聊宠物",
        ),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content="真好"),
        feeling=ExperienceFeeling(salience=0.6, emotion_label="好奇"),
        source="interaction",
    )
    stamp_anchor_context(
        unit,
        AnchorUnitContext(
            direction=InteractionDirection.inbound,
            session_id="s1",
            interactor_id="alice",
        ),
    )
    return unit


def _event_unit() -> ExperienceUnit:
    return ExperienceUnit.make(
        situation=ExperienceSituation(
            perception="午后阳光落在书桌上",
            narration="独自整理笔记",
        ),
        action=ExperienceAction(kind=ExperienceActionKind.reasoning, content="回顾今天"),
        feeling=ExperienceFeeling(salience=0.55, emotion_label="平静"),
        source="narrative",
    )


def test_classify_anchor_vs_event():
    assert classify_experience(_anchor_unit()) == ExperienceKind.anchor
    assert classify_experience(_event_unit()) == ExperienceKind.event

    user_unit = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", perception="用户说你好"),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content="你好"),
        feeling=ExperienceFeeling(salience=0.5),
        source="user",
    )
    assert classify_experience(user_unit) == ExperienceKind.anchor


def test_social_anchor_ingest_links_core_and_parent():
    nodes = _MemStore()
    edges = _EdgeStore()
    parent = SocialNeighborhoodNode(
        interactor_id="alice",
        focus="旧对话",
        label="旧对话",
        content="之前聊过宠物",
    )
    nodes.put(parent)

    llm = _FakeLLM(
        {
            "focus": "宠物",
            "subjective_statement": "我记得用户说他养了一只猫",
            "label": "宠物",
            "parent_node_id": parent.id,
            "parent_reason": "同属生活细节",
            "emotion": "好奇",
            "emotion_intensity": 0.6,
            "valence": "neutral",
            "base_activation": 0.6,
        }
    )
    archiver = ExperienceArchiver(llm, nodes)
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        archiver,
    )
    created = social.ingest_anchor_experience(_anchor_unit())
    assert len(created) == 1
    assert isinstance(created[0], SocialNeighborhoodNode)
    assert created[0].content.startswith("我记得")
    assert any(e.edge_type == EdgeType.about for e in edges.edges)
    assert any(
        e.edge_type == EdgeType.related_to and e.from_id == parent.id
        for e in edges.edges
    )


def test_read_experience_block_carries_experience_id():
    unit = _anchor_unit()
    block = read_experience_block(unit)
    assert block.experience_id == unit.id
    assert block.interactor_id == "alice"
