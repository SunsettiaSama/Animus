from __future__ import annotations

from config.knowledge.config import KnowledgeConfig
from knowledge.cache import KnowledgeCache
from knowledge.embedder import KnowledgeEmbedder
from knowledge.store import KnowledgeStore
from knowledge.vector_store import KnowledgeVectorStore


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += chunk_size - chunk_overlap
    return chunks


class KnowledgeIngestion:
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

    # ── Public API ────────────────────────────────────────────────────────────

    def ingest_text(
        self,
        text: str,
        source: str = "manual",
        source_type: str = "text",
        title: str = "",
        meta: dict | None = None,
        store_blob: bool = False,
    ) -> str:
        doc_id = self._store.insert_document(
            source=source,
            source_type=source_type,
            title=title,
            meta=meta,
        )
        if store_blob:
            self._store.insert_blob(doc_id, text)
        self._ingest_chunks(doc_id, text, meta or {})
        return doc_id

    def ingest_file(
        self,
        path: str,
        source_type: str | None = None,
        title: str = "",
        meta: dict | None = None,
    ) -> str:
        import os

        ext = os.path.splitext(path)[1].lower()
        if source_type is None:
            source_type = {
                ".pdf": "pdf",
                ".md": "markdown",
                ".txt": "text",
                ".csv": "csv",
            }.get(ext, "text")

        text = self._read_file(path, source_type)
        doc_id = self._store.insert_document(
            source=path,
            source_type=source_type,
            title=title or os.path.basename(path),
            meta=meta,
        )
        self._store.insert_blob(doc_id, text)
        self._ingest_chunks(doc_id, text, meta or {})
        return doc_id

    def delete_document(self, doc_id: str) -> None:
        self._store.delete_document(doc_id)
        self._vs.delete_by_doc(doc_id)
        self._cache.incr_version()

    def repair(self) -> int:
        chunks = self._store.get_unindexed_chunks()
        if not chunks:
            return 0
        self._embed_and_upsert(chunks)
        return len(chunks)

    def rebuild(self) -> int:
        chunks = self._store.get_all_active_chunks()
        if not chunks:
            return 0
        self._embed_and_upsert(chunks)
        self._cache.incr_version()
        return len(chunks)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_file(self, path: str, source_type: str) -> str:
        if source_type == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _ingest_chunks(self, doc_id: str, text: str, base_meta: dict) -> None:
        raw_chunks = _chunk_text(text, self._cfg.chunk_size, self._cfg.chunk_overlap)
        chunk_tuples = [(i, c, base_meta) for i, c in enumerate(raw_chunks)]

        self._store.update_document_status(doc_id, "chunked")
        chunk_ids = self._store.insert_chunks(doc_id, chunk_tuples)

        texts = [c for _, c, _ in chunk_tuples]
        vectors = self._embedder.embed_documents(texts)

        self._vs.upsert_batch(
            chunk_ids=chunk_ids,
            vectors=vectors,
            doc_ids=[doc_id] * len(chunk_ids),
            chunk_indexes=[i for i, _, _ in chunk_tuples],
            contents=texts,
            metas=[m for _, _, m in chunk_tuples],
        )

        self._store.mark_chunks_indexed(chunk_ids)
        self._store.update_document_status(doc_id, "indexed")
        self._cache.set_doc_status(doc_id, "indexed")
        self._cache.incr_version()

    def _embed_and_upsert(self, chunks: list) -> None:
        texts = [c.content for c in chunks]
        vectors = self._embedder.embed_documents(texts)
        self._vs.upsert_batch(
            chunk_ids=[c.id for c in chunks],
            vectors=vectors,
            doc_ids=[c.doc_id for c in chunks],
            chunk_indexes=[c.chunk_index for c in chunks],
            contents=texts,
            metas=[c.meta for c in chunks],
        )
        self._store.mark_chunks_indexed([c.id for c in chunks])
