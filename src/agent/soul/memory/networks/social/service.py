from __future__ import annotations

from typing import Callable

from agent.soul.life.experience.unit import ExperienceUnit
from agent.soul.memory.domain import EvolutionSource, SocialCoreNode, SocialNeighborhoodNode
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.networks.social.core_evolution import CoreEvolver
from agent.soul.memory.networks.social.neighborhood_ingest import NeighborhoodIngestor
from agent.soul.memory.ports import GraphEdgeStore, GraphNodeStore, InteractorStore, VectorIndexPort
from agent.soul.memory.processors.neighborhood_extractor import NeighborhoodExtractorPort


class SocialMemoryNetwork:
    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        interactors: InteractorStore,
        extractor: NeighborhoodExtractorPort,
        *,
        vectors: VectorIndexPort | None = None,
        on_written: Callable[[SocialNeighborhoodNode | SocialCoreNode], None] | None = None,
    ) -> None:
        self._nodes = nodes
        self._interactors = interactors
        self._vectors = vectors
        self._on_written = on_written
        self._extractor = extractor
        traversal = GraphTraversal(edges)
        self._core_evolver = CoreEvolver()
        self._neighborhood = NeighborhoodIngestor(nodes, traversal, extractor)

    def ensure_core(self, interactor_id: str) -> SocialCoreNode:
        self._interactors.get_or_create(interactor_id)
        existing = self._nodes.get_core_for_interactor(interactor_id)
        if existing is not None and isinstance(existing, SocialCoreNode):
            return existing
        core = SocialCoreNode(
            interactor_id=interactor_id,
            focus=f"对{interactor_id}的印象",
            core_traits="",
        )
        self._nodes.put(core)
        if self._on_written is not None:
            self._on_written(core)
        return core

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

    def ingest_interaction(
        self,
        unit: ExperienceUnit,
        *,
        interactor_id: str,
    ) -> list[SocialNeighborhoodNode]:
        core = self.ensure_core(interactor_id)
        candidates = self._extractor.extract(unit)
        nodes = self._neighborhood.ingest(core, candidates)
        for node in nodes:
            self._index_node(node)
        return nodes

    def _index_node(self, node: SocialNeighborhoodNode | SocialCoreNode) -> None:
        if self._vectors is None:
            return
        text = node.embed_text()
        if text.strip():
            self._vectors.upsert(node.id, text, network=node.network)
