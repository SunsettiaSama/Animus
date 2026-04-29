from __future__ import annotations

import threading

import torch
from langchain_community.embeddings import HuggingFaceBgeEmbeddings

from config.knowledge.config import KnowledgeConfig


class KnowledgeEmbedder:
    def __init__(self, cfg: KnowledgeConfig) -> None:
        self._cfg = cfg
        self._embeddings: HuggingFaceBgeEmbeddings | None = None
        self._lock = threading.Lock()

    def _get(self) -> HuggingFaceBgeEmbeddings:
        with self._lock:
            if self._embeddings is None:
                device = self._cfg.device
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                inner: dict = {"low_cpu_mem_usage": False}
                if self._cfg.use_fp16 and device != "cpu":
                    inner["torch_dtype"] = torch.float16
                self._embeddings = HuggingFaceBgeEmbeddings(
                    model_name=self._cfg.embedding_model,
                    model_kwargs={"device": device, "model_kwargs": inner},
                    encode_kwargs={
                        "normalize_embeddings": True,
                        "batch_size": self._cfg.batch_size,
                    },
                    embed_instruction=self._cfg.passage_prefix,
                    query_instruction=self._cfg.query_prefix,
                )
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get().embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._get().embed_query(query)
