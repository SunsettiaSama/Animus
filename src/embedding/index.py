from __future__ import annotations

import json
import os

import faiss
import numpy as np


def build_faiss_index(vectors: np.ndarray) -> faiss.IndexFlatIP:
    vectors = vectors.astype("float32")
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    return index


def save(
    output_dir: str,
    index: faiss.IndexFlatIP,
    chunks_meta: list[dict],
    index_filename: str,
    meta_filename: str,
) -> None:
    os.makedirs(output_dir, exist_ok=True)
    faiss.write_index(index, os.path.join(output_dir, index_filename))
    with open(os.path.join(output_dir, meta_filename), "w", encoding="utf-8") as f:
        for item in chunks_meta:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def load(
    output_dir: str,
    index_filename: str = "index.faiss",
    meta_filename: str = "meta.jsonl",
) -> tuple[faiss.IndexFlatIP, list[dict]]:
    index = faiss.read_index(os.path.join(output_dir, index_filename))
    meta: list[dict] = []
    with open(os.path.join(output_dir, meta_filename), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                meta.append(json.loads(line))
    return index, meta


def search(
    index: faiss.IndexFlatIP,
    meta: list[dict],
    query_vector: np.ndarray,
    top_k: int = 5,
) -> list[dict]:
    query_vector = query_vector.astype("float32")
    if query_vector.ndim == 1:
        query_vector = query_vector[np.newaxis, :]
    faiss.normalize_L2(query_vector)
    scores, indices = index.search(query_vector, top_k)
    results: list[dict] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue
        item = dict(meta[idx])
        item["score"] = float(score)
        results.append(item)
    return results
