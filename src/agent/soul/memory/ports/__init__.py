from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agent.soul.memory.domain import (
    ActivationCue,
    ActivationSnapshot,
    EdgeType,
    EvolutionSource,
    GraphNode,
    InteractorRef,
    MemoryEdge,
    MemoryNetwork,
    SocialCoreNode,
    SocialNeighborhoodNode,
    SocialNodeRole,
)

if TYPE_CHECKING:
    from agent.soul.life.experience.unit import ExperienceUnit
    from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
    from agent.soul.memory.networks.event.service import MemoryBlock


@runtime_checkable
class GraphNodeStore(Protocol):
    def put(self, node: GraphNode) -> None: ...
    def get(self, node_id: str) -> GraphNode | None: ...
    def get_many(self, node_ids: list[str]) -> list[GraphNode]: ...
    def list_by_network(self, network: MemoryNetwork, *, limit: int = 50) -> list[GraphNode]: ...
    def list_by_interactor(
        self,
        interactor_id: str,
        role: SocialNodeRole | None = None,
        *,
        limit: int = 50,
    ) -> list[GraphNode]: ...
    def archive(self, node_id: str) -> None: ...
    def on_recall(self, node_id: str) -> None: ...
    def add_rehearsal(self, node_id: str) -> None: ...
    def get_by_life_event_id(self, life_event_id: str) -> GraphNode | None: ...
    def get_core_for_interactor(self, interactor_id: str) -> GraphNode | None: ...
    def query_by_fields(self, **kwargs) -> list[GraphNode]: ...
    def list_recent(self, memory_type: str | None = None, valence=None, network: MemoryNetwork | None = None, limit: int = 50) -> list[GraphNode]: ...
    def list_all(self, limit: int = 2000, network: MemoryNetwork | None = None) -> list[GraphNode]: ...
    def add_narrative_ref(self, node_id: str) -> None: ...
    def forget_scan(
        self,
        *,
        threshold: float,
        half_life_days: float,
        dry_run: bool,
    ) -> list[str]: ...


@runtime_checkable
class GraphEdgeStore(Protocol):
    def put(self, edge: MemoryEdge) -> None: ...
    def out_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]: ...
    def in_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]: ...
    def delete_by_node(self, node_id: str) -> None: ...


@runtime_checkable
class InteractorStore(Protocol):
    def get_or_create(self, interactor_id: str, *, display_name: str = "") -> InteractorRef: ...
    def get(self, interactor_id: str) -> InteractorRef | None: ...


@runtime_checkable
class VectorIndexPort(Protocol):
    def upsert(self, node_id: str, text: str, *, network: MemoryNetwork) -> None: ...
    def search(
        self,
        vector: list[float],
        top_k: int,
        *,
        network: MemoryNetwork | None = None,
    ) -> list[tuple[str, float]]: ...
    def remove(self, node_id: str) -> None: ...
    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class SocialMemoryPort(Protocol):
    def ensure_core(self, interactor_id: str) -> SocialCoreNode: ...
    def evolve_core(
        self,
        interactor_id: str,
        *,
        delta: str,
        source: EvolutionSource,
        evidence_ids: list[str] | None = None,
    ) -> SocialCoreNode: ...
    def ingest_interaction(
        self,
        unit: ExperienceUnit,
        *,
        interactor_id: str,
    ) -> list[SocialNeighborhoodNode]: ...


@runtime_checkable
class EventMemoryPort(Protocol):
    def ingest_experience(self, unit: ExperienceUnit) -> GraphNode: ...
    def retract_experience(self, life_event_id: str) -> bool: ...
    def ruminate(
        self,
        node_id: str,
        *,
        trigger: str,
        emotional_context: str,
    ) -> GraphNode | None: ...
    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        *,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> GraphNode | None: ...
    def recall(self, query: str, top_k: int, emotional_context: str = "") -> MemoryBlock: ...
    def forget_scan(self, threshold: float | None, dry_run: bool) -> list[str]: ...
    def tick_heartbeat(self, snapshot) -> MemoryHeartbeatResult: ...


@runtime_checkable
class MemoryActivationPort(Protocol):
    def activate_async(self, cue: ActivationCue) -> None: ...
    def get_snapshot(self, session_id: str) -> ActivationSnapshot | None: ...
