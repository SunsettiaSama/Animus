from __future__ import annotations

from agent.soul.life.experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.memory.domain import EdgeType, MemoryEdge, SocialCoreNode, SocialNeighborhoodNode, SocialNodeRole
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.networks.social.neighborhood_ingest import NeighborhoodIngestor
from agent.soul.memory.networks.social.service import SocialMemoryNetwork
from agent.soul.memory.processors.neighborhood_extractor import NeighborhoodCandidate
from agent.soul.memory.processors.rule_neighborhood_extractor import RuleNeighborhoodExtractor


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

    def get_core_for_interactor(self, interactor_id: str):
        nodes = self.list_by_interactor(interactor_id, SocialNodeRole.core, limit=1)
        return nodes[0] if nodes else None

    def archive(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)

    def on_recall(self, node_id: str) -> None:
        pass

    def add_rehearsal(self, node_id: str) -> None:
        pass

    def get_by_life_event_id(self, life_event_id: str):
        return None

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


def test_social_network_isolates_interactors():
    nodes = _MemStore()
    edges = _EdgeStore()
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        RuleNeighborhoodExtractor(),
    )
    core_a = social.ensure_core("alice")
    core_b = social.ensure_core("bob")
    assert core_a.id != core_b.id
    assert core_a.interactor_id == "alice"


def test_neighborhood_ingest_creates_about_edges():
    nodes = _MemStore()
    edges = _EdgeStore()
    core = SocialCoreNode(interactor_id="alice", focus="印象", core_traits="")
    nodes.put(core)
    ingestor = NeighborhoodIngestor(nodes, GraphTraversal(edges), RuleNeighborhoodExtractor())
    created = ingestor.ingest(
        core,
        [
            NeighborhoodCandidate(label="宠物", content="养猫"),
            NeighborhoodCandidate(label="小黑", content="猫的名字", related_labels=["宠物"]),
        ],
    )
    assert created
    assert any(e.edge_type == EdgeType.about and e.from_id == core.id for e in edges.edges)
    assert any(e.edge_type == EdgeType.related_to for e in edges.edges)


def test_ingest_interaction_from_experience_unit():
    nodes = _MemStore()
    edges = _EdgeStore()
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        RuleNeighborhoodExtractor(),
    )
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id="s1",
            perception="用户：我养了一只猫叫小黑",
            narration="聊宠物",
        ),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content="真好"),
        feeling=ExperienceFeeling(salience=0.6, emotion_label="好奇"),
        source="interaction",
    )
    nodes_out = social.ingest_interaction(unit, interactor_id="alice")
    assert nodes_out
    assert isinstance(social.ensure_core("alice"), SocialCoreNode)
