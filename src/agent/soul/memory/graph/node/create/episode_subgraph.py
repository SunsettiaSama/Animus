from __future__ import annotations

from dataclasses import dataclass

from agent.soul.life.experience.domain.episode import (
    EpisodeItemType,
    LandmarkEpisode,
    TypedMemoryItemDraft,
)
from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.memory.domain.enums import Valence
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.graph.node.create.archive import ExperienceArchiver
from agent.soul.memory.graph.node.create.persist import NodePersister
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.ports import GraphEdgeStore, VectorIndexPort


@dataclass(frozen=True)
class EpisodeSubgraphResult:
    root: FactualMemory
    nodes: list[FactualMemory]


class EpisodeSubgraphIngest:
    """Landmark episode → 确定性 episode 子图（不交给 LLM 选父节点）。"""

    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        persister: NodePersister,
        archiver: ExperienceArchiver,
        *,
        vectors: VectorIndexPort | None = None,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._persister = persister
        self._archiver = archiver
        self._vectors = vectors
        self._traversal = GraphTraversal(edges)

    def ingest(
        self,
        unit: ExperienceUnit,
        episode: LandmarkEpisode,
        *,
        agent_persona_narrative: str = "",
    ) -> EpisodeSubgraphResult:
        existing = self._nodes.get_by_life_event_id(unit.id)
        if existing is not None and isinstance(existing, FactualMemory):
            linked = self._collect_subgraph_nodes(existing.id)
            return EpisodeSubgraphResult(root=existing, nodes=linked)

        root = self._build_node(
            unit=unit,
            episode=episode,
            item=TypedMemoryItemDraft(
                item_id=episode.episode_id,
                item_type=EpisodeItemType.episode,
                text=episode.summary_text()[:240] or unit.situation.narration[:240],
                focus=episode.intention[:12] or "地标经历",
                scene_id=episode.scene_id,
            ),
            life_event_id=unit.id,
        )
        self._persister.put_only(root)
        self._persister.notify(root)

        node_map: dict[str, FactualMemory] = {root.id: root}
        step_nodes: dict[int, FactualMemory] = {}
        observation_nodes: list[FactualMemory] = []

        for item in episode.typed_memory_items:
            if item.item_type == EpisodeItemType.episode:
                continue
            node = self._build_node(
                unit=unit,
                episode=episode,
                item=item,
                life_event_id="",
            )
            self._persister.put_only(node)
            self._persister.notify(node)
            node_map[item.item_id] = node
            if item.item_type == EpisodeItemType.arc_step:
                step_nodes[item.source_arc_step or item.step_index] = node
            if item.item_type == EpisodeItemType.observation:
                observation_nodes.append(node)

        for item in episode.typed_memory_items:
            if item.item_type == EpisodeItemType.episode:
                continue
            node = node_map.get(item.item_id)
            if node is None:
                continue
            if item.item_type == EpisodeItemType.arc_step:
                self._traversal.link_involves(root.id, node.id, weight=0.9)
                self._traversal.link_related_to(node.id, root.id, weight=0.7)
            elif item.item_type in {
                EpisodeItemType.observation,
                EpisodeItemType.subjective_reaction,
            }:
                parent = step_nodes.get(item.source_arc_step or item.step_index)
                if parent is not None:
                    self._traversal.link_source_of(parent.id, node.id, weight=0.9)
                    self._traversal.link_related_to(node.id, parent.id, weight=0.7)
            elif item.item_type == EpisodeItemType.lesson_or_hypothesis:
                parent = self._find_observation_for_lesson(
                    item,
                    observation_nodes,
                    step_nodes,
                )
                if parent is not None:
                    self._traversal.link_source_of(parent.id, node.id, weight=0.9)
                    self._traversal.link_related_to(node.id, parent.id, weight=0.7)

        self._link_related_episodes(root, episode, agent_persona_narrative=agent_persona_narrative)
        linked = self._collect_subgraph_nodes(root.id)
        return EpisodeSubgraphResult(root=root, nodes=linked)

    def _build_node(
        self,
        *,
        unit: ExperienceUnit,
        episode: LandmarkEpisode,
        item: TypedMemoryItemDraft,
        life_event_id: str,
    ) -> FactualMemory:
        node_id = item.item_id if item.item_type != EpisodeItemType.episode else unit.id
        if item.item_type == EpisodeItemType.episode:
            node_id = unit.id
        return FactualMemory(
            id=node_id,
            focus=item.focus or item.item_type.value[:12],
            fact=item.text[:500],
            perception=item.text[:120],
            emotion=unit.feeling.emotion_label,
            emotion_intensity=unit.feeling.salience,
            valence=Valence.neutral,
            base_activation=max(0.35, unit.feeling.salience),
            life_event_id=life_event_id,
            meta={
                "source_experience_id": unit.id,
                "episode_id": episode.episode_id,
                "episode_item_type": item.item_type.value,
                "scene_id": item.scene_id or episode.scene_id,
                "landmark_id": episode.landmark_id,
                "memory_item_id": item.item_id,
                "is_hypothesis": item.is_hypothesis,
                "arc_step_index": item.source_arc_step or item.step_index,
            },
        )

    def _find_observation_for_lesson(
        self,
        item: TypedMemoryItemDraft,
        observations: list[FactualMemory],
        step_nodes: dict[int, FactualMemory],
    ) -> FactualMemory | None:
        step_index = item.source_arc_step or item.step_index
        for node in observations:
            if int(node.meta.get("arc_step_index") or 0) == step_index:
                return node
        if step_index in step_nodes:
            return step_nodes[step_index]
        return observations[0] if observations else None

    def _collect_subgraph_nodes(self, root_id: str) -> list[FactualMemory]:
        collected: list[FactualMemory] = []
        root = self._nodes.get(root_id)
        if root is None or not isinstance(root, FactualMemory):
            return collected
        collected.append(root)
        seen = {root_id}
        queue = [root_id]
        while queue:
            current = queue.pop(0)
            for edge in self._edges.out_edges(current):
                if edge.to_id in seen:
                    continue
                node = self._nodes.get(edge.to_id)
                if node is None or not isinstance(node, FactualMemory):
                    continue
                seen.add(edge.to_id)
                collected.append(node)
                queue.append(edge.to_id)
        return collected

    def _link_related_episodes(
        self,
        root: FactualMemory,
        episode: LandmarkEpisode,
        *,
        agent_persona_narrative: str = "",
    ) -> None:
        _ = agent_persona_narrative
        if self._vectors is None:
            return
        query = episode.summary_text().strip()
        if not query:
            return
        vector = self._vectors.embed_query(query)
        if not vector:
            return
        hits = self._vectors.search(vector, top_k=4)
        for node_id, score in hits:
            if score < 0.22 or node_id == root.id:
                continue
            candidate = self._nodes.get(node_id)
            if candidate is None:
                continue
            meta = candidate.meta or {}
            if meta.get("episode_item_type") != EpisodeItemType.episode.value:
                continue
            other_scene = str(meta.get("scene_id") or "")
            if episode.scene_id and other_scene and episode.scene_id != other_scene:
                continue
            self._traversal.link_related_to(root.id, node_id, weight=0.5)
            self._traversal.link_related_to(node_id, root.id, weight=0.5)
