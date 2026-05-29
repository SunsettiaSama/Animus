from __future__ import annotations

from typing import Callable

from agent.soul.life.experience.unit import ExperienceUnit
from agent.soul.memory.domain.enums import MemoryNetwork
from agent.soul.memory.graph.base_node import BaseNode

from .node import FactualMemory
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.graph.networks.archival import ExperienceArchiver
from agent.soul.memory.graph.networks.block import MemoryBlock
from agent.soul.memory.graph.networks.experience_block import ExperienceBlock as IngestBlock
from agent.soul.memory.graph.networks.experience_block import read_experience_block
from agent.soul.memory.graph.networks.forget import NetworkForgetEngine
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.ports import GraphEdgeStore, VectorIndexPort
from agent.soul.memory.graph.networks.writer import NarrativeWriter
from config.soul.memory.service_config import MemoryServiceConfig


class EventMemoryNetwork:
    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        query: QueryEngine,
        narrative: NarrativeWriter,
        cfg: MemoryServiceConfig,
        archiver: ExperienceArchiver,
        *,
        vectors: VectorIndexPort | None = None,
        on_written: Callable[[BaseNode], None] | None = None,
        enqueue_recall: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._nodes = nodes
        self._traversal = GraphTraversal(edges)
        self._query = query
        self._narrative = narrative
        self._cfg = cfg
        self._archiver = archiver
        self._forget = NetworkForgetEngine()
        self._vectors = vectors
        self._on_written = on_written
        self._enqueue_recall = enqueue_recall

    def ingest_event_experience(
        self,
        unit: ExperienceUnit,
        *,
        block: IngestBlock | None = None,
    ) -> FactualMemory:
        block = block or read_experience_block(unit)
        existing = self._nodes.get_by_life_event_id(block.experience_id)
        if existing is not None and isinstance(existing, FactualMemory):
            return existing

        archived = self._archiver.archive_event(block)
        mem = archived.node
        self._nodes.put(mem)
        if archived.parent_node_id:
            self._traversal.link_related_to(archived.parent_node_id, mem.id)
        self._index(mem)
        return mem

    def retract_experience(self, life_event_id: str) -> bool:
        if not life_event_id:
            return False
        unit = self._nodes.get_by_life_event_id(life_event_id)
        if unit is None:
            return False
        self._nodes.archive(unit.id)
        if self._vectors is not None:
            self._vectors.remove(unit.id)
        return True

    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        *,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ):
        narrative = self._narrative.write(
            source_unit_ids=source_unit_ids,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )
        if narrative is not None:
            for sid in narrative.source_ids:
                self._traversal.link_weaves(narrative.id, sid)
        return narrative

    def ingest_narrative_from_units(
        self,
        source_units: list[BaseNode],
        chapter: str,
        *,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ):
        narrative = self._narrative.write_from_units(
            source_units=source_units,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )
        if narrative is not None:
            for sid in narrative.source_ids:
                self._traversal.link_weaves(narrative.id, sid)
        return narrative

    def recall(
        self,
        query: str,
        top_k: int,
        emotional_context: str = "",
    ) -> MemoryBlock:
        _ = emotional_context
        scored = self._query.hybrid(query=query, top_k=top_k)
        unit_ids = [s.unit.id for s in scored]
        if unit_ids and self._enqueue_recall is not None:
            self._enqueue_recall(lambda: self._on_recall_batch(unit_ids))
        entries = [s.render_line() for s in scored]
        return MemoryBlock(label="????", entries=entries)

    def forget_scan(self, threshold: float | None, dry_run: bool) -> list[str]:
        resolved = threshold if threshold is not None else self._cfg.forget_threshold
        return self._forget.forget_scan(
            self._nodes,
            threshold=resolved,
            half_life_days=self._cfg.half_life_days,
            dry_run=dry_run,
            network=MemoryNetwork.event,
            vectors=self._vectors,
        )

    def _index(self, node: BaseNode) -> None:
        if self._on_written is not None:
            self._on_written(node)

    def _on_recall_batch(self, unit_ids: list[str]) -> None:
        for uid in unit_ids:
            self._nodes.on_recall(uid)
