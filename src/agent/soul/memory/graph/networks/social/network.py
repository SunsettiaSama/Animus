from __future__ import annotations

from typing import Callable

from agent.soul.life.experience.unit import ExperienceUnit
from agent.soul.memory.domain import (
    EvolutionSource,
    MemoryNetwork,
    SocialCoreNode,
    SocialNeighborhoodNode,
    SocialNodeRole,
)
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.graph.networks.archival import ExperienceArchiver
from agent.soul.memory.graph.networks.experience_block import ExperienceBlock, read_experience_block
from agent.soul.memory.graph.networks.forget import NetworkForgetEngine
from agent.soul.memory.graph.networks.social.core_evolution import CoreEvolver
from agent.soul.memory.ports import GraphEdgeStore, GraphNodeStore, InteractorStore, VectorIndexPort


class SocialMemoryNetwork:
    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        interactors: InteractorStore,
        archiver: ExperienceArchiver,
        *,
        vectors: VectorIndexPort | None = None,
        on_written: Callable[[SocialNeighborhoodNode | SocialCoreNode], None] | None = None,
    ) -> None:
        self._nodes = nodes
        self._interactors = interactors
        self._vectors = vectors
        self._on_written = on_written
        self._archiver = archiver
        self._forget = NetworkForgetEngine()
        self._traversal = GraphTraversal(edges)
        self._core_evolver = CoreEvolver()

    def evolve_core(
        self,
        interactor_id: str,
        *,
        delta: str,
        source: EvolutionSource,
        evidence_ids: list[str] | None = None,
    ) -> SocialCoreNode:
        core = self.ensure_core(interactor_id)
        core = self._core_evolver.evolve(core, delta=delta, source=source)
        if evidence_ids:
            core.meta = {**core.meta, "evidence_ids": list(evidence_ids)}
        self._nodes.put(core)
        if self._on_written is not None:
            self._on_written(core)
        return core

    def ingest_anchor_experience(
        self,
        unit: ExperienceUnit,
        *,
        block: ExperienceBlock | None = None,
    ) -> list[SocialNeighborhoodNode]:
        block = block or read_experience_block(unit)
        existing = self._nodes.get_by_life_event_id(block.experience_id)
        if existing is not None and isinstance(existing, SocialNeighborhoodNode):
            return [existing]

        core = self.ensure_core(block.interactor_id)
        archived = self._archiver.archive_anchor(block)
        node = archived.node
        merged = self._merge_neighborhood(core, node)
        if archived.parent_node_id and archived.parent_node_id != merged.id:
            self._traversal.link_related_to(archived.parent_node_id, merged.id)
        self._index_node(merged)
        return [merged]

    def forget_scan(
        self,
        threshold: float,
        half_life_days: float,
        *,
        dry_run: bool = False,
    ) -> list[str]:
        return self._forget.forget_scan(
            self._nodes,
            threshold=threshold,
            half_life_days=half_life_days,
            dry_run=dry_run,
            network=MemoryNetwork.social,
            vectors=self._vectors,
        )

    def ensure_core(self, interactor_id: str) -> SocialCoreNode:
        self._interactors.get_or_create(interactor_id)
        existing = self._nodes.get_core_for_interactor(interactor_id)
        if existing is not None and isinstance(existing, SocialCoreNode):
            return existing
        core = SocialCoreNode(
            interactor_id=interactor_id,
            focus=f"对{interactor_id}的坰�?,
            core_traits="",
        )
        self._nodes.put(core)
        if self._on_written is not None:
            self._on_written(core)
        return core

    def _merge_neighborhood(
        self,
        core: SocialCoreNode,
        node: SocialNeighborhoodNode,
    ) -> SocialNeighborhoodNode:
        label_key = node.label.strip().lower()
        existing_nodes = self._nodes.list_by_interactor(
            core.interactor_id,
            SocialNodeRole.neighborhood,
            limit=200,
        )
        for existing in existing_nodes:
            if not isinstance(existing, SocialNeighborhoodNode):
                continue
            if existing.label.strip().lower() != label_key:
                continue
            if node.content.strip() and node.content not in existing.content:
                existing.content = f"{existing.content}\n{node.content}".strip()
                existing.focus = existing.label[:60] or existing.content[:60]
            existing.meta = {**existing.meta, **node.meta}
            self._nodes.put(existing)
            self._traversal.link_about(core.id, existing.id)
            return existing

        self._nodes.put(node)
        self._traversal.link_about(core.id, node.id)
        if self._on_written is not None:
            self._on_written(node)
        return node

    def _index_node(self, node: SocialNeighborhoodNode | SocialCoreNode) -> None:
        if self._vectors is None:
            return
        self._vectors.record(node)
