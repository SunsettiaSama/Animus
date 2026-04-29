from __future__ import annotations

import threading

import torch
from langchain_community.embeddings import HuggingFaceBgeEmbeddings

BGE_DIMS: dict[str, int] = {
    "large": 1024,
    "base": 768,
    "small": 512,
}


def infer_dim(model_name: str) -> int:
    name = model_name.lower()
    for key, dim in BGE_DIMS.items():
        if key in name:
            return dim
    return 512


class Embedder:
    def __init__(
        self,
        model_name: str,
        device: str = "auto",
        use_fp16: bool = True,
        batch_size: int = 32,
        query_prefix: str = "query: ",
        passage_prefix: str = "",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._use_fp16 = use_fp16
        self._batch_size = batch_size
        self._query_prefix = query_prefix
        self._passage_prefix = passage_prefix
        self._embeddings: HuggingFaceBgeEmbeddings | None = None
        self._lock = threading.Lock()

    def _get(self) -> HuggingFaceBgeEmbeddings:
        with self._lock:
            if self._embeddings is None:
                device = self._device
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                inner: dict = {"low_cpu_mem_usage": False}
                if self._use_fp16 and device != "cpu":
                    inner["torch_dtype"] = torch.float16
                self._embeddings = HuggingFaceBgeEmbeddings(
                    model_name=self._model_name,
                    model_kwargs={"device": device, "model_kwargs": inner},
                    encode_kwargs={
                        "normalize_embeddings": True,
                        "batch_size": self._batch_size,
                    },
                    embed_instruction=self._passage_prefix,
                    query_instruction=self._query_prefix,
                )
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get().embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._get().embed_query(query)
