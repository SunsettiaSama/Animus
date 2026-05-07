from __future__ import annotations

import threading
from typing import Tuple

import torch
from langchain_huggingface import HuggingFaceEmbeddings

BGE_DIMS: dict[str, int] = {
    "large": 1024,
    "base": 768,
    "small": 512,
}

# ── Shared HuggingFaceEmbeddings registry ─────────────────────────────────────
# Loading a SentenceTransformer model takes ~2 s and allocates significant GPU/
# CPU memory.  All Embedder instances that share the same (model, device,
# use_fp16) configuration reuse one underlying HuggingFaceEmbeddings object so
# the model is only loaded once — regardless of how many ConvLoop / TaoLoop /
# LongTermStore instances are created (WebUI session, bot sessions, …).

_HF_REGISTRY: dict[Tuple, HuggingFaceEmbeddings] = {}
_HF_REGISTRY_LOCK = threading.Lock()

_EmbedKey = Tuple[str, str, bool, int, str, str]


def _make_hf_key(
    model_name: str,
    device: str,
    use_fp16: bool,
    batch_size: int,
    query_prefix: str,
    passage_prefix: str,
) -> _EmbedKey:
    # Resolve "auto" at registration time so cpu vs cuda variants are distinct.
    resolved = device if device != "auto" else (
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    return (model_name, resolved, use_fp16, batch_size, query_prefix, passage_prefix)


def _get_or_create_hf(key: _EmbedKey) -> HuggingFaceEmbeddings:
    with _HF_REGISTRY_LOCK:
        if key not in _HF_REGISTRY:
            model_name, device, use_fp16, batch_size, query_prefix, passage_prefix = key
            model_kwargs: dict = {"device": device}
            if use_fp16 and device != "cpu":
                model_kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
            encode_kwargs: dict = {
                "normalize_embeddings": True,
                "batch_size": batch_size,
            }
            if passage_prefix:
                encode_kwargs["prompt"] = passage_prefix
            query_encode_kwargs: dict = {
                "normalize_embeddings": True,
                "batch_size": batch_size,
            }
            if query_prefix:
                query_encode_kwargs["prompt"] = query_prefix
            _HF_REGISTRY[key] = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs=model_kwargs,
                encode_kwargs=encode_kwargs,
                query_encode_kwargs=query_encode_kwargs,
            )
        return _HF_REGISTRY[key]


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
        self._key = _make_hf_key(
            model_name, device, use_fp16, batch_size, query_prefix, passage_prefix
        )

    def _get(self) -> HuggingFaceEmbeddings:
        return _get_or_create_hf(self._key)

    def warm_up(self) -> None:
        """Force-load the underlying SentenceTransformer model now.

        Safe to call from any thread; the registry lock prevents duplicate loads.
        After warm_up() returns, all other Embedder instances with the same
        configuration benefit immediately (shared HuggingFaceEmbeddings object).
        """
        self._get()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get().embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._get().embed_query(query)
