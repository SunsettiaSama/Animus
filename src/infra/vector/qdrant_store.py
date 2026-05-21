from __future__ import annotations

import os
import threading
import uuid

_CLIENT_REGISTRY: dict[str, object] = {}
_CLIENT_REGISTRY_LOCK = threading.Lock()


def _get_or_create_client(path: str):
    from qdrant_client import QdrantClient

    with _CLIENT_REGISTRY_LOCK:
        if path not in _CLIENT_REGISTRY:
            os.makedirs(path, exist_ok=True)
            _CLIENT_REGISTRY[path] = QdrantClient(path=path)
        return _CLIENT_REGISTRY[path]


def _point_id(unit_id: str) -> str:
    return str(uuid.UUID(unit_id))


class QdrantVectorStore:
    """Soul 记忆向量存储：本地 Qdrant 集合，point id 与 MemoryUnit.id 对齐。"""

    def __init__(
        self,
        *,
        qdrant_path: str,
        collection_name: str,
        vector_dim: int,
    ) -> None:
        self._qdrant_path = qdrant_path
        self._collection_name = collection_name
        self._vector_dim = vector_dim
        self._collection_ready = False
        self._lock = threading.RLock()

    @classmethod
    def build(
        cls,
        *,
        qdrant_path: str,
        collection_name: str,
        model_name_or_path: str,
    ) -> QdrantVectorStore:
        from embedding.embedder import infer_dim

        return cls(
            qdrant_path=qdrant_path,
            collection_name=collection_name,
            vector_dim=infer_dim(model_name_or_path),
        )

    def _client(self) -> QdrantClient:
        from qdrant_client import QdrantClient

        return _get_or_create_client(self._qdrant_path)

    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        client = self._client()
        with self._lock:
            if self._collection_ready:
                return
            existing = {c.name for c in client.get_collections().collections}
            if self._collection_name in existing:
                info = client.get_collection(self._collection_name)
                stored_dim = info.config.params.vectors.size
                if stored_dim != self._vector_dim:
                    client.delete_collection(self._collection_name)
                    existing.discard(self._collection_name)
            if self._collection_name not in existing:
                client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(
                        size=self._vector_dim,
                        distance=Distance.COSINE,
                    ),
                )
            self._collection_ready = True

    def upsert(self, unit_id: str, vector: list[float]) -> None:
        from qdrant_client.models import PointStruct

        self.ensure_collection()
        point = PointStruct(
            id=_point_id(unit_id),
            vector=vector,
            payload={"unit_id": unit_id},
        )
        self._client().upsert(collection_name=self._collection_name, points=[point])

    def delete(self, unit_id: str) -> None:
        from qdrant_client.models import PointIdsList

        self.ensure_collection()
        self._client().delete(
            collection_name=self._collection_name,
            points_selector=PointIdsList(points=[_point_id(unit_id)]),
        )

    def search(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        self.ensure_collection()
        hits = self._client().query_points(
            collection_name=self._collection_name,
            query=vector,
            limit=top_k,
            with_payload=True,
        ).points
        out: list[tuple[str, float]] = []
        for hit in hits:
            payload = hit.payload or {}
            unit_id = str(payload.get("unit_id") or hit.id)
            out.append((unit_id, float(hit.score)))
        return out
