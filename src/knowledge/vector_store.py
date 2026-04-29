from __future__ import annotations

import os
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from config.knowledge.config import KnowledgeConfig
from embedding.embedder import infer_dim


@dataclass
class SearchResult:
    chunk_id: str
    doc_id: str
    chunk_index: int
    content: str
    score: float
    meta: dict


class KnowledgeVectorStore:
    def __init__(self, cfg: KnowledgeConfig):
        self._cfg = cfg
        os.makedirs(cfg.qdrant_path, exist_ok=True)
        self._client = QdrantClient(path=cfg.qdrant_path)
        self._dim: int | None = None

    def _get_dim(self) -> int:
        if self._dim is None:
            self._dim = infer_dim(self._cfg.embedding_model)
        return self._dim

    def ensure_collection(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self._cfg.collection_name not in existing:
            self._client.create_collection(
                collection_name=self._cfg.collection_name,
                vectors_config=VectorParams(
                    size=self._get_dim(), distance=Distance.COSINE
                ),
            )

    def upsert_batch(
        self,
        chunk_ids: list[str],
        vectors: list[list[float]],
        doc_ids: list[str],
        chunk_indexes: list[int],
        contents: list[str],
        metas: list[dict],
    ) -> None:
        points = [
            PointStruct(
                id=cid,
                vector=vec,
                payload={
                    "doc_id": did,
                    "chunk_index": cidx,
                    "content": content,
                    **meta,
                },
            )
            for cid, vec, did, cidx, content, meta in zip(
                chunk_ids, vectors, doc_ids, chunk_indexes, contents, metas
            )
        ]
        self._client.upsert(collection_name=self._cfg.collection_name, points=points)

    def search(
        self,
        vector: list[float],
        top_k: int,
        doc_id_filter: str | None = None,
    ) -> list[SearchResult]:
        query_filter: Filter | None = None
        if doc_id_filter:
            query_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id_filter))]
            )
        hits = self._client.query_points(
            collection_name=self._cfg.collection_name,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        ).points
        results = []
        for hit in hits:
            payload = hit.payload or {}
            extra = {
                k: v
                for k, v in payload.items()
                if k not in ("doc_id", "chunk_index", "content")
            }
            results.append(
                SearchResult(
                    chunk_id=str(hit.id),
                    doc_id=payload.get("doc_id", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    content=payload.get("content", ""),
                    score=float(hit.score),
                    meta=extra,
                )
            )
        return results

    def delete_by_doc(self, doc_id: str) -> None:
        self._client.delete(
            collection_name=self._cfg.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                )
            ),
        )

    def delete_by_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self._client.delete(
            collection_name=self._cfg.collection_name,
            points_selector=PointIdsList(points=chunk_ids),
        )

    def count(self) -> int:
        info = self._client.get_collection(self._cfg.collection_name)
        return info.points_count or 0
