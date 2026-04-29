from __future__ import annotations

from config.knowledge.config import KnowledgeConfig
from knowledge.cache import KnowledgeCache
from knowledge.embedder import KnowledgeEmbedder
from knowledge.ingestion import KnowledgeIngestion
from knowledge.retriever import KnowledgeRetriever, RetrievalResult
from knowledge.store import KnowledgeStore
from knowledge.vector_store import KnowledgeVectorStore


class KnowledgeBase:
    def __init__(
        self,
        cfg: KnowledgeConfig,
        store: KnowledgeStore,
        vector_store: KnowledgeVectorStore,
        cache: KnowledgeCache,
        embedder: KnowledgeEmbedder,
        ingestion: KnowledgeIngestion,
        retriever: KnowledgeRetriever,
    ):
        self.cfg = cfg
        self.store = store
        self.vector_store = vector_store
        self.cache = cache
        self.embedder = embedder
        self.ingestion = ingestion
        self.retriever = retriever

    @classmethod
    def from_config(cls, cfg: KnowledgeConfig) -> KnowledgeBase:
        store = KnowledgeStore(cfg)
        vs = KnowledgeVectorStore(cfg)
        cache = KnowledgeCache(cfg)
        embedder = KnowledgeEmbedder(cfg)
        ingestion = KnowledgeIngestion(cfg, store, vs, cache, embedder)
        retriever = KnowledgeRetriever(cfg, store, vs, cache, embedder)
        return cls(cfg, store, vs, cache, embedder, ingestion, retriever)

    def setup(self) -> None:
        self.store.init_schema()
        self.vector_store.ensure_collection()

    def repair(self) -> int:
        return self.ingestion.repair()

    def rebuild(self) -> int:
        return self.ingestion.rebuild()

    def ingest_text(
        self,
        text: str,
        source: str = "manual",
        source_type: str = "text",
        title: str = "",
        meta: dict | None = None,
        store_blob: bool = False,
    ) -> str:
        return self.ingestion.ingest_text(text, source, source_type, title, meta, store_blob)

    def ingest_file(
        self,
        path: str,
        source_type: str | None = None,
        title: str = "",
        meta: dict | None = None,
    ) -> str:
        return self.ingestion.ingest_file(path, source_type, title, meta)

    def delete(self, doc_id: str) -> None:
        self.ingestion.delete_document(doc_id)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        doc_id_filter: str | None = None,
    ) -> list[RetrievalResult]:
        return self.retriever.search(query, top_k, doc_id_filter)

    def search_keyword(
        self,
        query: str,
        top_k: int | None = None,
        domain: str | None = None,
    ) -> list[RetrievalResult]:
        return self.retriever.search_keyword(query, top_k, domain)

    def search_semantic(
        self,
        query: str,
        top_k: int | None = None,
        doc_id_filter: str | None = None,
        domain: str | None = None,
    ) -> list[RetrievalResult]:
        return self.retriever.search_semantic(query, top_k, doc_id_filter, domain)

    def hybrid_search(
        self,
        query: str,
        top_k_each: int = 3,
        doc_id_filter: str | None = None,
        domain: str | None = None,
    ) -> list[RetrievalResult]:
        return self.retriever.search_hybrid(query, top_k_each, doc_id_filter, domain)


__all__ = [
    "KnowledgeBase",
    "KnowledgeConfig",
    "KnowledgeEmbedder",
    "RetrievalResult",
    "KnowledgeStore",
    "KnowledgeVectorStore",
    "KnowledgeCache",
    "KnowledgeIngestion",
    "KnowledgeRetriever",
]
