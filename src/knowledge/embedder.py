from __future__ import annotations

from embedding.embedder import Embedder
from config.knowledge.config import KnowledgeConfig


class KnowledgeEmbedder:
    def __init__(self, cfg: KnowledgeConfig) -> None:
        self._embedder = Embedder(
            model_name=cfg.embedding_model,
            device=cfg.device,
            use_fp16=cfg.use_fp16,
            batch_size=cfg.batch_size,
            query_prefix=cfg.query_prefix,
            passage_prefix=cfg.passage_prefix,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._embedder.embed_query(query)
