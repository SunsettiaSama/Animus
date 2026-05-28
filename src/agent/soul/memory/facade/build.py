from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.activation.service import ActivationService
from agent.soul.memory.domain import GraphNode
from agent.soul.memory.facade.adapters.life_ingest import LifeIngestAdapter
from agent.soul.memory.facade.adapters.speak_activation import SpeakActivationAdapter
from agent.soul.memory.facade.service import MemoryService
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.networks.event.service import EventMemoryNetwork
from agent.soul.memory.networks.social.service import SocialMemoryNetwork
from agent.soul.memory.processors.rule_neighborhood_extractor import RuleNeighborhoodExtractor
from agent.soul.memory.retriever import MemoryRetriever
from agent.soul.memory.store.mysql.edges import MySQLEdgeStore
from agent.soul.memory.store.mysql.interactors import MySQLInteractorStore
from agent.soul.memory.store.mysql.nodes import MySQLNodeStore
from agent.soul.memory.store.vector.qdrant import QdrantVectorIndex
from agent.soul.memory.writer.narrative_writer import NarrativeWriter
from agent.soul.memory.writer.rumination_writer import RuminationWriter
from config.soul.memory.service_config import MemoryServiceConfig
from infra.memory import MemoryInfraService

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient
    from infra.llm import BaseLLM


def build_memory_service(
    llm: BaseLLM,
    mysql_client: MySQLClient,
    cfg: MemoryServiceConfig | None = None,
    memory_infra: MemoryInfraService | None = None,
) -> MemoryService:
    if cfg is None:
        cfg = MemoryServiceConfig.load_default()

    infra = memory_infra or MemoryInfraService.build()
    nodes = MySQLNodeStore(mysql_client)
    edges = MySQLEdgeStore(mysql_client)
    interactors = MySQLInteractorStore(mysql_client)
    nodes.init_schema()

    vectors = QdrantVectorIndex(infra) if infra.enabled else None
    svc_holder: list[MemoryService] = []

    def _after_write(node: GraphNode) -> None:
        if svc_holder and vectors is not None and vectors.enabled:
            text = node.embed_text()
            if text.strip():
                uid = node.id
                svc_holder[0]._enqueue_write(
                    lambda u=uid, t=text, n=node.network: vectors.upsert(u, t, network=n)
                )

    rumination = RuminationWriter(llm, nodes, on_written=_after_write)
    narrative = NarrativeWriter(llm, nodes, on_written=_after_write)
    query = QueryEngine(
        nodes,
        recent_half_life_days=cfg.recent_half_life_days,
        half_life_days=cfg.half_life_days,
        vectors=vectors,
    )
    social = SocialMemoryNetwork(
        nodes,
        edges,
        interactors,
        RuleNeighborhoodExtractor(),
        vectors=vectors,
        on_written=_after_write,
    )
    event = EventMemoryNetwork(
        nodes,
        edges,
        query,
        rumination,
        narrative,
        cfg,
        vectors=vectors,
        on_written=_after_write,
    )
    activation = ActivationService(
        nodes,
        edges,
        vectors,
        threshold=cfg.activation_threshold,
        max_hops=cfg.activation_max_hops,
        hop_decay=cfg.activation_hop_decay,
        seed_top_k=cfg.activation_seed_top_k,
        keyword_weight=cfg.activation_keyword_weight,
    )
    life_ingest = LifeIngestAdapter(event, social)
    speak_activation = SpeakActivationAdapter(activation)
    retriever = MemoryRetriever(
        nodes,
        recent_half_life_days=cfg.recent_half_life_days,
        half_life_days=cfg.half_life_days,
        embedder=infra.retriever_embedder(),
        vector_store=infra.retriever_vector_store(),
    )
    svc = MemoryService(
        social,
        event,
        activation,
        life_ingest,
        speak_activation,
        retriever,
        cfg,
        nodes,
        memory_infra=infra,
    )
    svc_holder.append(svc)
    return svc


MemoryService.build = staticmethod(build_memory_service)
