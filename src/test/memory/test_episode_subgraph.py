from __future__ import annotations

from agent.soul.life.experience.domain.episode import EpisodeItemType, LandmarkEpisode, TypedMemoryItemDraft
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.graph.node.create.episode_subgraph import EpisodeSubgraphIngest
from agent.soul.memory.graph.node.create.persist import NodePersister
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.ports import GraphEdgeStore, MemoryEdge


class _MemoryNodeStore:
    def __init__(self) -> None:
        self._nodes: dict[str, FactualMemory] = {}

    def put(self, node: FactualMemory) -> None:
        self._nodes[node.id] = node

    def get(self, node_id: str) -> FactualMemory | None:
        return self._nodes.get(node_id)

    def get_by_life_event_id(self, life_event_id: str) -> FactualMemory | None:
        for node in self._nodes.values():
            if node.life_event_id == life_event_id:
                return node
        return None


class _MemoryEdgeStore(GraphEdgeStore):
    def __init__(self) -> None:
        self.edges: list[MemoryEdge] = []

    def put(self, edge: MemoryEdge) -> None:
        self.edges.append(edge)

    def out_edges(self, node_id: str):
        return [edge for edge in self.edges if edge.from_id == node_id]

    def in_edges(self, node_id: str):
        return [edge for edge in self.edges if edge.to_id == node_id]


def test_episode_subgraph_writes_deterministic_edges():
    nodes = _MemoryNodeStore()
    edges = _MemoryEdgeStore()
    persister = NodePersister(nodes, vectors=None, on_written=None)
    ingest = EpisodeSubgraphIngest(nodes, edges, persister, archiver=object())
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(narration="完整日志"),
        action=ExperienceAction(kind=ExperienceActionKind.deciding, content="复核"),
        feeling=ExperienceFeeling(salience=0.7, emotion_label="专注"),
    )
    episode = LandmarkEpisode(
        episode_id="ep-1",
        experience_id=unit.id,
        landmark_id="lm-1",
        intention="复核岩棚",
        scene_id="scene-rock",
        objective_summary="发现湿度异常",
        typed_memory_items=[
            TypedMemoryItemDraft(
                item_id=unit.id,
                item_type=EpisodeItemType.episode,
                text="复核岩棚发现湿度异常",
                focus="岩棚复核",
                scene_id="scene-rock",
            ),
            TypedMemoryItemDraft(
                item_id="step-1",
                item_type=EpisodeItemType.arc_step,
                text="读数偏高",
                focus="第1拍",
                scene_id="scene-rock",
                source_arc_step=1,
            ),
            TypedMemoryItemDraft(
                item_id="obs-1",
                item_type=EpisodeItemType.observation,
                text="湿度读数偏高",
                focus="湿度",
                scene_id="scene-rock",
                source_arc_step=1,
            ),
        ],
    )
    result = ingest.ingest(unit, episode)
    assert result.root.id == unit.id
    traversal = GraphTraversal(edges)
    assert any(edge.edge_type.value == "involves" for edge in edges.edges)
    assert any(edge.edge_type.value == "source_of" for edge in edges.edges)
    linked = traversal.bfs({result.root.id: 1.0}, max_hops=2, hop_decay=0.8, threshold=0.1)
    assert len(linked) >= 2
