from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.graph.base_node import BaseNode
from agent.soul.memory.emergence import Emergence, SpeakEmergence, SpreadActivationService
from agent.soul.memory.emergence.dispatcher import EmergenceQueryDispatcher
from agent.soul.memory.facade.service import MemoryService
from agent.soul.memory.graph.cluster import ClusterIndex
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.graph.node.create.archive import ArchivalConfig, ExperienceArchiver
from agent.soul.memory.graph.networks.event.network import EventMemoryNetwork
from agent.soul.memory.graph.networks.semantic_index import SemanticVectorIndex
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.networks.social.query import SocialQueryEngine
from agent.soul.memory.graph.networks.store.mysql.edges import MySQLEdgeStore
from agent.soul.memory.graph.networks.store.mysql.interactors import MySQLInteractorStore
from agent.soul.memory.graph.networks.store.mysql.nodes import MySQLNodeStore
from agent.soul.memory.graph.networks.store.mysql.session_channels import MySQLSessionChannelStore
from agent.soul.memory.graph.networks.store.json import (
    JsonEdgeStore,
    JsonInteractorStore,
    JsonNodeStore,
    JsonSessionChannelStore,
)
from agent.soul.memory.graph.networks.writer import NarrativeWriter
from agent.soul.memory.rumination import RuminationService, RuminationWriter
from agent.soul.memory.retriever import MemoryRetriever
from agent.soul.memory.io.session import SessionMemoryBuffer, SessionMemoryChannel
from agent.soul.memory.sleep import SleepConfig, SleepService
from config.soul.memory.infra_config import SoulMemoryInfraConfig
from config.soul.memory.service_config import MemoryServiceConfig
from infra.memory import MemoryInfraService
from infra.storage import JsonStorageService

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient
    from infra.llm import BaseLLM


def build_memory_service(
    llm: BaseLLM,
    mysql_client: MySQLClient | None = None,
    cfg: MemoryServiceConfig | None = None,
    memory_infra: MemoryInfraService | None = None,
    storage_backend: str = "mysql",
    json_root: str = ".react/soul_db",
) -> MemoryService:
    if cfg is None:
        cfg = MemoryServiceConfig.load_default()

    backend = storage_backend.strip().lower()
    if backend == "json":
        storage = JsonStorageService(json_root)
        infra = memory_infra or MemoryInfraService(
            cfg=SoulMemoryInfraConfig(enabled=False),
            embedding=None,
            vectors=None,
        )
        nodes = JsonNodeStore(storage)
        edges = JsonEdgeStore(storage)
        interactors = JsonInteractorStore(storage)
        session_channels = JsonSessionChannelStore(storage)
        nodes.init_schema()
    else:
        if mysql_client is None:
            raise RuntimeError("mysql storage backend requires mysql_client")
        infra = memory_infra or MemoryInfraService.build()
        nodes = MySQLNodeStore(mysql_client)
        edges = MySQLEdgeStore(mysql_client)
        interactors = MySQLInteractorStore(mysql_client)
        session_channels = MySQLSessionChannelStore(mysql_client)
        nodes.init_schema()

    vectors = SemanticVectorIndex(infra) if infra.enabled else SemanticVectorIndex(None)
    from agent.soul.memory.domain import MemoryNetwork

    for node in nodes.list_by_network(MemoryNetwork.social, limit=5000):
        vectors.rehydrate(node)
    cluster_index = ClusterIndex(
        similarity_threshold=cfg.cluster_similarity_threshold,
        min_cluster_size=cfg.cluster_min_size,
        core_probe_top_k=cfg.cluster_core_top_k,
        cache_path=cfg.cluster_cache_path,
    )
    cluster_index.try_load_cache()
    query = QueryEngine(
        nodes,
        recent_half_life_days=cfg.recent_half_life_days,
        half_life_days=cfg.half_life_days,
        vectors=vectors,
        cluster_index=cluster_index,
        cluster_core_top_k=cfg.cluster_core_top_k,
    )
    query_dispatcher = EmergenceQueryDispatcher(max_workers=cfg.emergence_query_workers)
    spread = SpreadActivationService(
        nodes,
        edges,
        vectors,
        query,
        cluster_index,
        threshold=cfg.activation_threshold,
        max_hops=cfg.activation_max_hops,
        hop_decay=cfg.activation_hop_decay,
        seed_top_k=cfg.activation_seed_top_k,
        keyword_weight=cfg.activation_keyword_weight,
        cluster_core_top_k=cfg.cluster_core_top_k,
        hot_seed_top_k=cfg.hot_seed_top_k,
        hot_max_hops=cfg.hot_max_hops,
        point_top_k=cfg.point_query_top_k,
        associative_sigma=cfg.associative_sigma,
        hybrid_w_relevance=cfg.hybrid_w_relevance,
        hybrid_w_activation=cfg.hybrid_w_activation,
        speak_line_max_content=cfg.speak_memory_line_max_content,
        query_submit=query_dispatcher.submit,
    )
    svc_holder: list[MemoryService] = []

    def _after_write(node: BaseNode) -> None:
        if not svc_holder or not vectors.enabled:
            return

        def _task() -> None:
            vectors.record(node)
            spread.schedule_cluster_rebuild()

        svc_holder[0]._enqueue_write(_task)

    archiver = ExperienceArchiver(
        llm,
        nodes,
        vectors=vectors,
        cfg=ArchivalConfig(
            candidate_k=getattr(cfg, "archive_candidate_k", 5),
            min_similarity=getattr(cfg, "archive_min_similarity", 0.20),
        ),
    )
    rumination_writer = RuminationWriter(llm, nodes, on_written=_after_write)
    narrative = NarrativeWriter(llm, nodes, on_written=_after_write)
    social_query = SocialQueryEngine(
        nodes,
        half_life_days=cfg.half_life_days,
        vectors=vectors,
        w_relevance=cfg.hybrid_w_relevance,
        w_activation=cfg.hybrid_w_activation,
    )
    social = SocialMemoryNetwork(
        nodes,
        edges,
        interactors,
        archiver,
        vectors=vectors,
        query=social_query,
        on_written=_after_write,
    )
    event = EventMemoryNetwork(
        nodes,
        edges,
        query,
        narrative,
        cfg,
        archiver,
        vectors=vectors,
        on_written=_after_write,
    )
    emergence = Emergence(
        spread=spread,
        speak=SpeakEmergence(spread, use_point_query=cfg.speak_use_point_query),
    )
    retriever = MemoryRetriever(
        nodes,
        recent_half_life_days=cfg.recent_half_life_days,
        half_life_days=cfg.half_life_days,
        embedder=infra.retriever_embedder(),
        vector_store=infra.retriever_vector_store(),
    )
    rumination = RuminationService(
        nodes,
        edges,
        query,
        rumination_writer,
        narrative,
        spread,
        cfg,
    )
    sleep = SleepService(
        event,
        social,
        emergence,
        rumination,
        cfg,
        sleep_cfg=SleepConfig(
            buffer_decay=getattr(cfg, "sleep_buffer_decay", 0.85),
            buffer_drop_below=getattr(cfg, "sleep_buffer_drop_below", 0.08),
            sleep_emotion_threshold=getattr(cfg, "sleep_emotion_threshold", 0.55),
            consolidation_scan_limit=getattr(cfg, "sleep_consolidation_scan_limit", 500),
        ),
    )
    session_buffer = SessionMemoryBuffer(
        nodes=nodes,
        edges=edges,
        social=social,
        social_query=social_query,
        archiver=archiver,
        llm=llm,
        vectors=vectors,
    )
    session_channel = SessionMemoryChannel(buffer=session_buffer)
    svc = MemoryService(
        social,
        event,
        emergence,
        rumination,
        sleep,
        retriever,
        cfg,
        nodes,
        memory_infra=infra,
        query_dispatcher=query_dispatcher,
        session_buffer=session_buffer,
        session_channel=session_channel,
        session_channels=session_channels,
        llm=llm,
    )
    svc_holder.append(svc)
    spread.schedule_cluster_rebuild()
    return svc


MemoryService.build = staticmethod(build_memory_service)
