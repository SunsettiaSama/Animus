from __future__ import annotations

import threading

import torch
from langchain_huggingface import HuggingFaceEmbeddings

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
        self._embeddings: HuggingFaceEmbeddings | None = None
        self._lock = threading.Lock()

    def _get(self) -> HuggingFaceEmbeddings:
        with self._lock:
            if self._embeddings is None:
                device = self._device
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                # model_kwargs keys are forwarded as **kwargs to SentenceTransformer.__init__.
                # Parameters for the underlying HuggingFace model (e.g. torch_dtype)
                # must be nested under the "model_kwargs" key, which SentenceTransformer
                # then passes to AutoModel.from_pretrained(**model_kwargs).
                model_kwargs: dict = {"device": device}
                if self._use_fp16 and device != "cpu":
                    model_kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
                encode_kwargs: dict = {
                    "normalize_embeddings": True,
                    "batch_size": self._batch_size,
                }
                if self._passage_prefix:
                    encode_kwargs["prompt"] = self._passage_prefix
                query_encode_kwargs: dict = {
                    "normalize_embeddings": True,
                    "batch_size": self._batch_size,
                }
                if self._query_prefix:
                    query_encode_kwargs["prompt"] = self._query_prefix
                self._embeddings = HuggingFaceEmbeddings(
                    model_name=self._model_name,
                    model_kwargs=model_kwargs,
                    encode_kwargs=encode_kwargs,
                    query_encode_kwargs=query_encode_kwargs,
                )
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get().embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._get().embed_query(query)
