from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config.soul.memory.infra_config import SoulMemoryInfraConfig
from infra.embedding import EmbeddingService
from infra.vector import QdrantVectorStore

if TYPE_CHECKING:
    from agent.soul.memory.retriever import EmbedderBackend, VectorBackend


@dataclass
class MemoryInfraService:
    """Soul 记忆基础设施门面：Embedding + Qdrant，经 MemoryService 统一调用。"""

    cfg: SoulMemoryInfraConfig
    embedding: EmbeddingService | None
    vectors: QdrantVectorStore | None

    @classmethod
    def build(cls, cfg: SoulMemoryInfraConfig | None = None) -> MemoryInfraService:
        resolved = cfg or SoulMemoryInfraConfig.load_default()
        if not resolved.enabled:
            return cls(cfg=resolved, embedding=None, vectors=None)
        embedding = EmbeddingService(
            model_name_or_path=resolved.model_name_or_path,
            device=resolved.device,
            use_fp16=resolved.use_fp16,
            batch_size=resolved.batch_size,
            query_prefix=resolved.query_prefix,
            passage_prefix=resolved.passage_prefix,
        )
        vectors = QdrantVectorStore.build(
            qdrant_path=resolved.qdrant_path,
            collection_name=resolved.collection_name,
            model_name_or_path=resolved.model_name_or_path,
        )
        return cls(cfg=resolved, embedding=embedding, vectors=vectors)

    def warm_up(self) -> None:
        if self.embedding is None:
            return
        self.embedding.warm_up()
        if self.vectors is not None:
            self.vectors.ensure_collection()

    @property
    def enabled(self) -> bool:
        return (
            self.cfg.enabled
            and self.embedding is not None
            and self.vectors is not None
        )

    def index_unit(self, unit_id: str, text: str) -> None:
        if not self.enabled:
            return
        vector = self.embedding.embed_passage(text)
        self.vectors.upsert(unit_id, vector)

    def remove_unit(self, unit_id: str) -> None:
        if self.vectors is None:
            return
        self.vectors.delete(unit_id)

    def retriever_embedder(self) -> EmbedderBackend | None:
        if self.embedding is None:
            return None
        embedding = self.embedding

        class _Adapter:
            def embed(self, text: str) -> list[float]:
                return embedding.embed_query(text)

        return _Adapter()

    def retriever_vector_store(self) -> VectorBackend | None:
        return self.vectors
