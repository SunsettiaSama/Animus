from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from config.knowledge.config import KnowledgeConfig
from knowledge.cache import KnowledgeCache
from knowledge.embedder import KnowledgeEmbedder
from knowledge.store import KnowledgeStore
from knowledge.vector_store import KnowledgeVectorStore, SearchResult


@dataclass
class RetrievalResult:
    chunk_id: str
    doc_id: str
    chunk_index: int
    content: str
    score: float
    source: str  # "mysql" | "qdrant_payload" | "keyword_fts" | "fallback_fts"
    meta: dict


class KnowledgeRetriever:
    def __init__(
        self,
        cfg: KnowledgeConfig,
        store: KnowledgeStore,
        vector_store: KnowledgeVectorStore,
        cache: KnowledgeCache,
        embedder: KnowledgeEmbedder | None = None,
    ):
        self._cfg = cfg
        self._store = store
        self._vs = vector_store
        self._cache = cache
        self._embedder = embedder if embedder is not None else KnowledgeEmbedder(cfg)

    # ── Original search (preserved for full compatibility) ────────────────────

    def search(
        self,
        query: str,
        top_k: int | None = None,
        doc_id_filter: str | None = None,
    ) -> list[RetrievalResult]:
        """Full degradation chain search (backward-compatible entry point).

        Degradation order:
          1. Redis cache (version-checked)
          2. Qdrant → MySQL (authoritative content)
          3. Qdrant payload content (MySQL unavailable)
          4. MySQL full-text search (Qdrant unavailable)
          5. Empty list
        """
        top_k = top_k or self._cfg.top_k

        if doc_id_filter is None:
            cached = self._cache.get_query(query, mode="semantic", top_k=top_k)
            if cached is not None:
                return [RetrievalResult(**r) for r in cached]

        qdrant_hits = self._qdrant_search(query, top_k, doc_id_filter)

        if qdrant_hits:
            mysql_results = self._enrich_from_mysql(qdrant_hits)
            if mysql_results:
                if doc_id_filter is None:
                    self._cache.set_query(
                        query,
                        [_result_to_dict(r) for r in mysql_results],
                        mode="semantic",
                        top_k=top_k,
                    )
                return mysql_results

            return [
                RetrievalResult(
                    chunk_id=r.chunk_id,
                    doc_id=r.doc_id,
                    chunk_index=r.chunk_index,
                    content=r.content,
                    score=r.score,
                    source="qdrant_payload",
                    meta=r.meta,
                )
                for r in qdrant_hits
            ]

        fts_chunks = self._store.fulltext_search(query, limit=top_k)
        if fts_chunks:
            return [
                RetrievalResult(
                    chunk_id=c.id,
                    doc_id=c.doc_id,
                    chunk_index=c.chunk_index,
                    content=c.content,
                    score=0.0,
                    source="fallback_fts",
                    meta=c.meta,
                )
                for c in fts_chunks
            ]

        return []

    # ── Keyword search ────────────────────────────────────────────────────────

    def search_keyword(
        self,
        query: str,
        top_k: int | None = None,
        domain: str | None = None,
    ) -> list[RetrievalResult]:
        top_k = top_k or self._cfg.top_k

        cached = self._cache.get_query(query, mode="keyword", top_k=top_k, domain=domain)
        if cached is not None:
            return [RetrievalResult(**r) for r in cached]

        fts_chunks = self._store.fulltext_search(query, limit=top_k)
        results = [
            RetrievalResult(
                chunk_id=c.id,
                doc_id=c.doc_id,
                chunk_index=c.chunk_index,
                content=c.content,
                score=0.0,
                source="keyword_fts",
                meta=c.meta,
            )
            for c in fts_chunks
        ]

        if results:
            self._cache.set_query(
                query,
                [_result_to_dict(r) for r in results],
                mode="keyword",
                top_k=top_k,
                domain=domain,
            )

        return results

    # ── Semantic search ───────────────────────────────────────────────────────

    def search_semantic(
        self,
        query: str,
        top_k: int | None = None,
        doc_id_filter: str | None = None,
        domain: str | None = None,
    ) -> list[RetrievalResult]:
        top_k = top_k or self._cfg.top_k

        if doc_id_filter is None:
            cached = self._cache.get_query(
                query, mode="semantic", top_k=top_k, domain=domain
            )
            if cached is not None:
                return [RetrievalResult(**r) for r in cached]

        qdrant_hits = self._qdrant_search(query, top_k, doc_id_filter)

        if qdrant_hits:
            mysql_results = self._enrich_from_mysql(qdrant_hits)
            if mysql_results:
                if doc_id_filter is None:
                    self._cache.set_query(
                        query,
                        [_result_to_dict(r) for r in mysql_results],
                        mode="semantic",
                        top_k=top_k,
                        domain=domain,
                    )
                return mysql_results

            return [
                RetrievalResult(
                    chunk_id=r.chunk_id,
                    doc_id=r.doc_id,
                    chunk_index=r.chunk_index,
                    content=r.content,
                    score=r.score,
                    source="qdrant_payload",
                    meta=r.meta,
                )
                for r in qdrant_hits
            ]

        fts_chunks = self._store.fulltext_search(query, limit=top_k)
        results = [
            RetrievalResult(
                chunk_id=c.id,
                doc_id=c.doc_id,
                chunk_index=c.chunk_index,
                content=c.content,
                score=0.0,
                source="fallback_fts",
                meta=c.meta,
            )
            for c in fts_chunks
        ]

        if results and doc_id_filter is None:
            self._cache.set_query(
                query,
                [_result_to_dict(r) for r in results],
                mode="semantic",
                top_k=top_k,
                domain=domain,
            )

        return results

    # ── Hybrid search ─────────────────────────────────────────────────────────

    def search_hybrid(
        self,
        query: str,
        top_k_each: int = 3,
        doc_id_filter: str | None = None,
        domain: str | None = None,
    ) -> list[RetrievalResult]:
        keyword_results: list[RetrievalResult] = []
        semantic_results: list[RetrievalResult] = []

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_kw = pool.submit(self.search_keyword, query, top_k_each, domain)
            fut_sem = pool.submit(
                self.search_semantic, query, top_k_each, doc_id_filter, domain
            )
            for fut in as_completed([fut_kw, fut_sem]):
                if fut is fut_kw:
                    keyword_results = fut.result()
                else:
                    semantic_results = fut.result()

        # semantic results take priority; keyword fills in unique chunks
        seen: set[str] = set()
        merged: list[RetrievalResult] = []

        for r in semantic_results[:top_k_each]:
            seen.add(r.chunk_id)
            merged.append(r)

        for r in keyword_results[:top_k_each]:
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                merged.append(r)

        merged.sort(key=lambda r: r.score, reverse=True)
        return merged

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _qdrant_search(
        self, query: str, top_k: int, doc_id_filter: str | None
    ) -> list[SearchResult] | None:
        vector = self._embedder.embed_query(query)
        return self._vs.search(vector=vector, top_k=top_k, doc_id_filter=doc_id_filter)

    def _enrich_from_mysql(
        self, qdrant_results: list[SearchResult]
    ) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []
        uncached_ids: list[str] = []

        # Check chunk cache first
        cache_hits: dict[str, str] = {}
        for r in qdrant_results:
            cached_content = self._cache.get_chunk(r.chunk_id)
            if cached_content is not None:
                cache_hits[r.chunk_id] = cached_content
            else:
                uncached_ids.append(r.chunk_id)

        # Fetch only uncached chunks from MySQL
        chunk_map: dict[str, object] = {}
        if uncached_ids:
            chunks = self._store.get_chunks_by_ids(uncached_ids)
            for c in chunks:
                chunk_map[c.id] = c
                self._cache.set_chunk(c.id, c.content)

        for r in qdrant_results:
            if r.chunk_id in cache_hits:
                content = cache_hits[r.chunk_id]
                results.append(
                    RetrievalResult(
                        chunk_id=r.chunk_id,
                        doc_id=r.doc_id,
                        chunk_index=r.chunk_index,
                        content=content,
                        score=r.score,
                        source="mysql",
                        meta=r.meta,
                    )
                )
            elif r.chunk_id in chunk_map:
                chunk = chunk_map[r.chunk_id]
                results.append(
                    RetrievalResult(
                        chunk_id=r.chunk_id,
                        doc_id=r.doc_id,
                        chunk_index=r.chunk_index,
                        content=chunk.content,
                        score=r.score,
                        source="mysql",
                        meta={**r.meta, **chunk.meta},
                    )
                )

        return results


def _result_to_dict(r: RetrievalResult) -> dict:
    return {
        "chunk_id": r.chunk_id,
        "doc_id": r.doc_id,
        "chunk_index": r.chunk_index,
        "content": r.content,
        "score": r.score,
        "source": r.source,
        "meta": r.meta,
    }
