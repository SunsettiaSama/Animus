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


def infer_dim(model_name_or_path: str) -> int:
    """Return the actual output embedding dimension for *model_name_or_path*.

    Resolution order (stops at the first hit):
    1. ``2_Dense/config.json`` → ``out_features``
       A Dense layer genuinely changes output dimensionality; always authoritative.
    2. ``config.json`` → ``hidden_size``
       The transformer's hidden size IS the embedding dimension when no Dense
       layer exists.  Reading the pooling config's ``word_embedding_dimension``
       before this would give wrong results if the config file is stale/mixed.
    3. ``1_Pooling/config.json`` → ``word_embedding_dimension``
       Fallback for ST pipelines that lack a top-level config.json.
    4. Name-keyword fallback: "large" → 1024, "base" → 768, "small" → 512
    5. Hard default: 768
    """
    import json
    import os

    # ── 1. Dense layer output dimension (most authoritative) ─────────────────
    dense_cfg = os.path.join(model_name_or_path, "2_Dense", "config.json")
    if os.path.isfile(dense_cfg):
        with open(dense_cfg, encoding="utf-8") as f:
            dc = json.load(f)
        if "out_features" in dc:
            return int(dc["out_features"])

    # ── 2. HuggingFace transformer config (actual hidden size) ───────────────
    hf_cfg = os.path.join(model_name_or_path, "config.json")
    if os.path.isfile(hf_cfg):
        with open(hf_cfg, encoding="utf-8") as f:
            mc = json.load(f)
        if "hidden_size" in mc:
            return int(mc["hidden_size"])

    # ── 3. sentence-transformers pooling config (fallback) ───────────────────
    pooling_cfg = os.path.join(model_name_or_path, "1_Pooling", "config.json")
    if os.path.isfile(pooling_cfg):
        with open(pooling_cfg, encoding="utf-8") as f:
            pc = json.load(f)
        if "word_embedding_dimension" in pc:
            return int(pc["word_embedding_dimension"])

    # ── 4. Name-keyword fallback ──────────────────────────────────────────────
    name = model_name_or_path.lower()
    for key, dim in BGE_DIMS.items():
        if key in name:
            return dim

    # ── 5. Hard default ───────────────────────────────────────────────────────
    return 768


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
                model_kwargs["model_kwargs"] = {"dtype": torch.float16, "attn_implementation": "eager"}
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
