from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import torch
from FlagEmbedding import FlagModel

from config.embedding.config import BuildConfig
from embedding.corpus import Chunk, build_chunks, load_csv
from embedding import index as idx_module


def _resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def _embed_chunks(
    chunks: list[Chunk],
    model: FlagModel,
    passage_prefix: str,
    batch_size: int,
) -> np.ndarray:
    texts = [passage_prefix + c.text for c in chunks]
    batches: list[np.ndarray] = []
    total = len(texts)
    for start in range(0, total, batch_size):
        batch = texts[start : start + batch_size]
        vecs = model.encode(batch)
        batches.append(np.array(vecs, dtype="float32"))
        done = min(start + batch_size, total)
        print(f"  embedding: {done}/{total}", end="\r", flush=True)
    print()
    return np.vstack(batches)


def build(cfg: BuildConfig) -> None:
    print(f"[1/4] loading corpus  →  {cfg.csv_path}")
    rows = load_csv(cfg.csv_path, cfg.text_column, cfg.extra_columns)
    print(f"      {len(rows)} rows loaded")

    print(f"[2/4] chunking  (size={cfg.chunk_size}, overlap={cfg.chunk_overlap})")
    chunks = build_chunks(rows, cfg.chunk_size, cfg.chunk_overlap)
    print(f"      {len(chunks)} chunks produced")

    device = _resolve_device(cfg.device)
    print(f"[3/4] embedding  model={cfg.model_name_or_path}  device={device}")
    model = FlagModel(
        cfg.model_name_or_path,
        use_fp16=cfg.use_fp16,
        device=device,
    )
    vectors = _embed_chunks(chunks, model, cfg.passage_prefix, cfg.batch_size)

    print("[4/4] building FAISS index and saving")
    faiss_index = idx_module.build_faiss_index(vectors)
    chunks_meta = [
        {"chunk_id": c.chunk_id, "source_row": c.source_row, "text": c.text, **c.meta}
        for c in chunks
    ]
    idx_module.save(
        cfg.output_dir,
        faiss_index,
        chunks_meta,
        cfg.index_filename,
        cfg.meta_filename,
    )
    print(f"      index  →  {cfg.output_dir}/{cfg.index_filename}")
    print(f"      meta   →  {cfg.output_dir}/{cfg.meta_filename}")
    print("done.")
