from __future__ import annotations

from typing import Callable

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.memory.domain.enums import EdgeType, EvolutionSource, MemoryNetwork
from agent.soul.memory.graph.networks.block import MemoryBlock
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.graph.node.create.archive import ExperienceArchiver
from agent.soul.memory.graph.node.create.persist import NodePersister
from agent.soul.memory.graph.node.maintain.forget import NodeForgetEngine
from agent.soul.memory.graph.node.modify.evolve import CoreEvolver
from agent.soul.memory.graph.node.modify.merge import merge_neighborhood
from agent.soul.memory.graph.networks.experience_block import ExperienceBlock, read_experience_block
from agent.soul.memory.graph.networks.social.portrait import InteractorPortrait
from agent.soul.memory.graph.networks.social.query import SocialQueryEngine
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.ports import GraphEdgeStore, InteractorStore, VectorIndexPort

from .node import SocialCoreNode, SocialNeighborhoodNode


class SocialMemoryNetwork:
    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        interactors: InteractorStore,
        archiver: ExperienceArchiver,
        *,
        vectors: VectorIndexPort | None = None,
        query: SocialQueryEngine | None = None,
        on_written: Callable[[SocialNeighborhoodNode | SocialCoreNode], None] | None = None,
    ) -> None:
        self._nodes = nodes
        self._interactors = interactors
        self._vectors = vectors
        self._query = query or SocialQueryEngine(nodes, vectors=vectors)
        self._on_written = on_written
        self._archiver = archiver
        self._persister = NodePersister(nodes, vectors=vectors, on_written=on_written)
        self._forget = NodeForgetEngine()
        self._traversal = GraphTraversal(edges)
        self._core_evolver = CoreEvolver()

    def register_core_portrait(
        self,
        interactor_id: str,
        portrait: InteractorPortrait | dict,
        *,
        agent_relation: str = "",
        display_name: str = "",
    ) -> SocialCoreNode:
        """Register or update interactor core portrait (PersonaProfile-shaped fields)."""
        self._interactors.get_or_create(interactor_id, display_name=display_name)
        profile = (
            portrait
            if isinstance(portrait, InteractorPortrait)
            else InteractorPortrait.from_dict(portrait)
        )
        if display_name.strip():
            profile.name = display_name.strip()
        core = self.ensure_core(interactor_id)
        core.portrait = profile
        if agent_relation.strip():
            core.agent_relation = agent_relation.strip()
        core.focus = f"\u5bf9{profile.name or interactor_id}\u7684\u5370\u8c61"
        return self._persister.write(core)

    def set_agent_relation(self, interactor_id: str, relation: str) -> SocialCoreNode:
        core = self.ensure_core(interactor_id)
        core.agent_relation = relation.strip()
        return self._persister.write(core)

    def merge_neighborhood(
        self,
        core: SocialCoreNode,
        node: SocialNeighborhoodNode,
    ) -> SocialNeighborhoodNode:
        return merge_neighborhood(
            nodes=self._nodes,
            traversal=self._traversal,
            persister=self._persister,
            core=core,
            node=node,
        )

    def write_node(
        self,
        node: SocialNeighborhoodNode | SocialCoreNode,
        *,
        embed: bool = True,
    ) -> SocialNeighborhoodNode | SocialCoreNode:
        return self._persister.write(node, embed=embed)

    def link_nodes(
        self,
        from_id: str,
        to_id: str,
        *,
        edge_type: EdgeType = EdgeType.related_to,
        weight: float = 0.9,
        bidirectional: bool = False,
    ) -> None:
        if edge_type == EdgeType.about:
            self._traversal.link_about(from_id, to_id, weight=weight)
        elif edge_type == EdgeType.involves:
            self._traversal.link_involves(from_id, to_id, weight=weight)
        else:
            self._traversal.link_related_to(from_id, to_id, weight=weight)
        if bidirectional:
            self.link_nodes(to_id, from_id, edge_type=edge_type, weight=weight, bidirectional=False)

    def link_interactor_relation(
        self,
        interactor_id: str,
        other_interactor_id: str,
        *,
        label: str,
        content: str,
    ) -> SocialNeighborhoodNode:
        """Record a social relation between two interactors and link both cores."""
        core_a = self.ensure_core(interactor_id)
        core_b = self.ensure_core(other_interactor_id)
        node = SocialNeighborhoodNode(
            interactor_id=interactor_id,
            focus=label[:60] or content[:60],
            label=label[:200],
            content=content,
            related_interactor_ids=[other_interactor_id],
        )
        merged = self.merge_neighborhood(core_a, node)
        self.link_nodes(merged.id, core_b.id, edge_type=EdgeType.related_to, bidirectional=True)
        self.link_nodes(core_a.id, merged.id, edge_type=EdgeType.about)
        return merged

    def add_supplement(
        self,
        interactor_id: str,
        *,
        label: str,
        content: str,
        related_interactor_ids: list[str] | None = None,
        link_core: bool = True,
    ) -> SocialNeighborhoodNode:
        core = self.ensure_core(interactor_id)
        node = SocialNeighborhoodNode(
            interactor_id=interactor_id,
            focus=label[:60] or content[:60],
            label=label[:200],
            content=content,
            related_interactor_ids=list(related_interactor_ids or []),
        )
        merged = self.merge_neighborhood(core, node)
        for other_id in node.related_interactor_ids:
            other_core = self.ensure_core(other_id)
            self.link_nodes(merged.id, other_core.id, edge_type=EdgeType.related_to)
        if not link_core:
            return merged
        return merged

    def resolve_interactor_for_tone(
        self,
        query: str,
        *,
        hinted_interactor_id: str = "",
        top_k: int = 12,
    ) -> tuple[str, SocialCoreNode | None]:
        from .interactor_resolve import resolve_likely_interactor_core

        return resolve_likely_interactor_core(
            self,
            query,
            hinted_interactor_id=hinted_interactor_id,
            top_k=top_k,
        )

    def probe_interactor_for_tone(
        self,
        query: str,
        *,
        hinted_interactor_id: str = "",
        top_k: int = 12,
        min_best_score: float = 0.12,
        max_score_gap: float = 0.20,
    ):
        from .interactor_resolve import probe_interactor_core

        return probe_interactor_core(
            self,
            query,
            hinted_interactor_id=hinted_interactor_id,
            top_k=top_k,
            min_best_score=min_best_score,
            max_score_gap=max_score_gap,
        )

    def render_interactor_portrait(
        self,
        interactor_id: str,
        core: SocialCoreNode,
    ) -> str:
        from .interactor_resolve import render_interactor_portrait_block

        return render_interactor_portrait_block(interactor_id, core)

    def gather_neighborhood_context(
        self,
        interactor_id: str,
        *,
        query: str = "",
        top_k: int = 4,
    ) -> tuple[tuple[str, float], ...]:
        from .neighborhood_context import gather_weighted_neighborhood_context

        return gather_weighted_neighborhood_context(
            self,
            interactor_id,
            query=query,
            top_k=top_k,
            event_time_half_life_days=self._query._event_time_hl,
        )

    def build_interactor_portrait_narrative(
        self,
        interactor_id: str,
        core: SocialCoreNode,
        *,
        query: str = "",
        user_text: str = "",
        top_k: int = 4,
    ) -> str:
        from .portrait_narrative import render_interactor_opening_narrative

        ranked = self.gather_neighborhood_context(
            interactor_id,
            query=query,
            top_k=top_k,
        )
        snippets = tuple(text for text, _score in ranked)
        changelog = core.trait_changelog.strip()
        recent_impression = ""
        if changelog:
            recent_impression = changelog.splitlines()[-1].strip()
        return render_interactor_opening_narrative(
            interactor_id=interactor_id,
            core=core,
            neighborhood_snippets=snippets,
            user_text=user_text,
            agent_relation=core.agent_relation.strip(),
            recent_impression=recent_impression,
        )

    def recall(
        self,
        query: str,
        top_k: int = 5,
        *,
        interactor_id: str = "",
    ) -> MemoryBlock:
        scored = self._query.recall(query, top_k, interactor_id=interactor_id)
        entries = [s.render_line() for s in scored]
        if interactor_id:
            label = f"\u793e\u4ea4\u8bb0\u5fc6\u00b7{interactor_id}"
        else:
            label = "\u793e\u4ea4\u8bb0\u5fc6"
        return MemoryBlock(label=label, entries=entries)

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
        return self._persister.write(core)

    def ingest_anchor_experience(
        self,
        unit: ExperienceUnit,
        *,
        block: ExperienceBlock | None = None,
        agent_persona_narrative: str = "",
    ) -> list[SocialNeighborhoodNode]:
        block = block or read_experience_block(unit)
        existing = self._nodes.get_by_life_event_id(block.experience_id)
        if existing is not None and isinstance(existing, SocialNeighborhoodNode):
            return [existing]

        core = self.ensure_core(block.interactor_id)
        archived = self._archiver.archive_anchor(
            block,
            agent_persona_narrative=agent_persona_narrative,
        )
        node = archived.node
        merged = self.merge_neighborhood(core, node)
        if archived.parent_node_id and archived.parent_node_id != merged.id:
            self._traversal.link_related_to(archived.parent_node_id, merged.id)
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
            focus=f"\u5bf9{interactor_id}\u7684\u5370\u8c61",
        )
        self._persister.write(core)
        return core
