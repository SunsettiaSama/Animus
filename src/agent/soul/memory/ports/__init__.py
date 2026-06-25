from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agent.soul.memory.domain import (
    ActivationCue,
    ActivationSnapshot,
    EdgeType,
    EvolutionSource,
    InteractorRef,
    MemoryEdge,
    MemoryNetwork,
    SocialCoreNode,
    SocialNeighborhoodNode,
    SocialNodeRole,
)
from agent.soul.memory.graph.base_node import BaseNode

if TYPE_CHECKING:
    from agent.soul.life.experience.domain.unit import ExperienceUnit
    from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
    from agent.soul.memory.graph.networks.block import MemoryBlock


@runtime_checkable
class GraphEdgeStore(Protocol):
    def put(self, edge: MemoryEdge) -> None: ...
    def out_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]: ...
    def in_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]: ...
    def delete_edge(self, edge_id: str) -> None: ...
    def delete_by_node(self, node_id: str) -> None: ...


@runtime_checkable
class InteractorStore(Protocol):
    def get_or_create(self, interactor_id: str, *, display_name: str = "") -> InteractorRef: ...
    def get(self, interactor_id: str) -> InteractorRef | None: ...


@runtime_checkable
class SessionChannelStore(Protocol):
    def get_interactor(self, session_id: str) -> str: ...
    def bind(self, session_id: str, interactor_id: str) -> None: ...


@runtime_checkable
class VectorIndexPort(Protocol):
    def record(self, node: BaseNode) -> None: ...
    def embed_passage(self, text: str) -> list[float]: ...
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
    def register_core_portrait(
        self,
        interactor_id: str,
        portrait: object,
        *,
        agent_relation: str = "",
        display_name: str = "",
    ) -> SocialCoreNode: ...
    def set_agent_relation(self, interactor_id: str, relation: str) -> SocialCoreNode: ...
    def link_interactor_relation(
        self,
        interactor_id: str,
        other_interactor_id: str,
        *,
        label: str,
        content: str,
    ) -> SocialNeighborhoodNode: ...
    def evolve_core(
        self,
        interactor_id: str,
        *,
        delta: str,
        source: EvolutionSource,
        evidence_ids: list[str] | None = None,
    ) -> SocialCoreNode: ...
    def recall(
        self,
        query: str,
        top_k: int = 5,
        *,
        interactor_id: str = "",
    ): ...
    def ingest_interaction(
        self,
        unit: ExperienceUnit,
        *,
        interactor_id: str,
    ) -> list[SocialNeighborhoodNode]: ...


@runtime_checkable
class EventMemoryPort(Protocol):
    def ingest_experience(self, unit: ExperienceUnit) -> BaseNode: ...
    def retract_experience(self, life_event_id: str) -> bool: ...
    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        *,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> BaseNode | None: ...
    def recall(self, query: str, top_k: int, emotional_context: str = "") -> MemoryBlock: ...
    def forget_scan(self, threshold: float | None, dry_run: bool) -> list[str]: ...


@runtime_checkable
class RuminationPort(Protocol):
    def ruminate(
        self,
        node_id: str,
        *,
        trigger: str,
        emotional_context: str,
    ) -> BaseNode | None: ...

    def tick(self, snapshot) -> MemoryHeartbeatResult: ...


@runtime_checkable
class MemoryEmergencePort(Protocol):
    def request_speak_point_query(
        self,
        *,
        session_id: str,
        interactor_id: str,
        turn_index: int,
        user_text: str,
        agent_text: str = "",
    ) -> None: ...

    def get_point_emergence(self, session_id: str, turn_index: int): ...

    def get_snapshot(self, session_id: str) -> ActivationSnapshot | None: ...
